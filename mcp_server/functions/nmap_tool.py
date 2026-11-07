import asyncio
import ipaddress
import re
import xml.etree.ElementTree as ET

NMAP_ARG_LIST = [
    "-Pn", "-sS",
    "--stats-every", "3m",
    "--max-retries", "1",
    "--max-scan-delay", "20",
    "--defeat-rst-ratelimit",
    "-T4",
    "-p1-65535",
]
SCAN_TIMEOUT = 3600
MAX_OPEN_PORTS_SHOWN = 200
DOMAIN_PATTERN = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")


def check_target_format(target):
    """校验 target 是单个 IP 或域名。格式正确返回 None，否则返回错误信息。"""
    try:
        ipaddress.ip_address(target)
        return None
    except ValueError:
        pass
    if DOMAIN_PATTERN.match(target):
        return None
    return f"错误: target 必须是单个 IP 地址或域名，收到: {target}"


def format_host_lines(host_node):
    """把一台主机的端口扫描结果格式化成若干行文本。"""
    host_ip = "unknown"
    for address_node in host_node.findall("address"):
        if address_node.get("addrtype") in ("ipv4", "ipv6"):
            host_ip = address_node.get("addr")
            break
    # 只保留用户传入的主机名（type="user"），忽略反向解析（type="PTR"）得到的名字
    user_hostname = ""
    for hostname_node in host_node.findall("hostnames/hostname"):
        if hostname_node.get("type") == "user":
            user_hostname = hostname_node.get("name")
            break

    title = f"主机 {host_ip}"
    if user_hostname:
        title += f" ({user_hostname})"
    line_list = [title]

    ports_node = host_node.find("ports")
    if ports_node is None:
        line_list.append("无端口信息")
        return line_list

    dict_state2count = {}
    for extra_node in ports_node.findall("extraports"):
        extra_state = extra_node.get("state")
        dict_state2count[extra_state] = dict_state2count.get(extra_state, 0) + int(extra_node.get("count", "0"))

    list_open_port = []
    for port_node in ports_node.findall("port"):
        state_node = port_node.find("state")
        port_state = state_node.get("state") if state_node is not None else "unknown"
        if port_state != "open":
            dict_state2count[port_state] = dict_state2count.get(port_state, 0) + 1
            continue
        service_node = port_node.find("service")
        service_name = service_node.get("name", "") if service_node is not None else ""
        if service_name == "unknown":
            service_name = ""
        list_open_port.append((int(port_node.get("portid")), port_node.get("protocol"), service_name))
    list_open_port.sort()

    summary = f"开放端口 {len(list_open_port)} 个"
    if dict_state2count:
        other_text = ", ".join(f"{state} {count}" for state, count in sorted(dict_state2count.items()))
        summary += f"; 其他端口: {other_text}"
    line_list.append(summary)

    if not list_open_port:
        line_list.append("未发现开放端口。因扫描使用 -Pn，无法区分“目标离线”和“所有端口被过滤”，请结合其他信息判断")
        return line_list

    line_list.append("注: 服务名由端口号查表得出，未经版本探测确认；服务名为空表示表中没有该端口")
    line_list.append("")

    list_shown_port = list_open_port[:MAX_OPEN_PORTS_SHOWN]
    list_port_text = [f"{port}/{protocol}" for port, protocol, service_name in list_shown_port]
    column_width = max(len(port_text) for port_text in list_port_text) + 4
    line_list.append("PORT".ljust(column_width) + "SERVICE")
    for port_text, (port, protocol, service_name) in zip(list_port_text, list_shown_port):
        if service_name:
            line_list.append(port_text.ljust(column_width) + service_name)
        else:
            line_list.append(port_text)
    if len(list_open_port) > MAX_OPEN_PORTS_SHOWN:
        line_list.append(f"...另有 {len(list_open_port) - MAX_OPEN_PORTS_SHOWN} 个开放端口未显示")
    return line_list

def parse_nmap_xml(xml_text: str) -> str:
    """把 nmap 的 XML 输出转成紧凑文本，可用样本 XML 离线测试。"""
    root = ET.fromstring(xml_text)
    host_node_list = root.findall("host")
    if not host_node_list:
        return "未获得主机信息"
    list_host_block = []
    for host_node in host_node_list:
        list_host_block.append("\n".join(format_host_lines(host_node)))
    return "\n\n".join(list_host_block)


async def scan_open_ports(target: str) -> str:
    """对目标做全端口（1-65535）TCP SYN 扫描，只判断端口是否开放，返回开放端口列表。不探测服务版本、系统和脚本信息，也不扫描 UDP。扫描耗时较长，可能需要几十分钟。
    target: 单个 IP 地址（IPv4 或 IPv6）或域名，如 10.10.10.48、scanme.nmap.org。不支持网段。
    """
    target_error = check_target_format(target)
    if target_error:
        return target_error

    list_arg = list(NMAP_ARG_LIST)
    if ":" in target:
        list_arg.append("-6")

    try:
        process = await asyncio.create_subprocess_exec(
            "nmap", *list_arg, "-oX", "-", target,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return "错误: 未找到 nmap，请先安装并加入 PATH"

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=SCAN_TIMEOUT)
    except asyncio.TimeoutError:
        return f"错误: 扫描超时 ({SCAN_TIMEOUT} 秒)"
    finally:
        # 超时、请求被取消等任何没有正常结束的情况，都要杀掉 nmap，否则它会留在后台继续扫描
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()

    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    if process.returncode != 0:
        return f"错误: nmap 执行失败: {stderr_text.strip()[:500]}"

    try:
        result_text = parse_nmap_xml(stdout_text)
    except ET.ParseError:
        return f"错误: 无法解析 nmap 输出: {stdout_text[:200]}"

    header = " ".join(["执行命令: nmap", *list_arg, target])
    return f"{header}\n\n{result_text}"


TOOLS = [scan_open_ports]