import requests, time, os, datetime, logging
import pytz
from collections import OrderedDict
from urllib.parse import quote

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

hf_token = os.environ["HF_TOKEN"]
username = os.environ["USERNAME"]
space_list_str = os.environ.get("SPACE_LIST", "")
space_list = [space.strip() for space in space_list_str.split(",") if space.strip()]
global_timeout_seconds = int(os.environ.get("GLOBAL_TIMEOUT_SECONDS", 1800))
repo_id = os.environ.get("GITHUB_REPOSITORY")

def check_space_with_browser_emulation(space_name):
    full_space_url = f"https://{username}-{space_name}.hf.space"
    logging.info(f"开始模拟浏览器访问空间: {full_space_url}")
    start_time = time.time()
    try:
        response = requests.get(full_space_url, timeout=30)
        response.raise_for_status()
        duration = time.time() - start_time
        logging.info(f"✅空间{space_name}访问正常, 耗时: {duration:.2f}秒")
        return True, duration
    except requests.exceptions.RequestException as e:
        duration = time.time() - start_time
        logging.error(f"❌空间{space_name}访问失败, 耗时: {duration:.2f}秒: {e}")
        return False, duration
    except Exception as e:
        duration = time.time() - start_time
        logging.exception(f"❌空间{space_name}发生未知错误, 耗时: {duration:.2f}秒: {e}")
        return False, duration

def rebuild_space(space_name):
    full_space_name = f"{username}/{space_name}"
    logging.info(f"开始重新构建空间: {full_space_name}")
    rebuild_url = f"https://huggingface.co/api/spaces/{full_space_name}/restart?factory=true"
    status_url = f"https://huggingface.co/api/spaces/{full_space_name}/runtime"

    headers = {"Authorization": f"Bearer {hf_token}", "Content-Type": "application/json"}

    start_time = time.time()
    try:
        response = requests.post(rebuild_url, headers=headers)
        response.raise_for_status()
        logging.info(f"✅空间{space_name}重新构建请求发送成功")
    except requests.exceptions.RequestException as e:
        duration = time.time() - start_time
        logging.error(f"❌空间{space_name}重新构建请求失败, 耗时: {duration:.2f}秒: {e}")
        return False, duration

    attempt = 0
    max_attempts = 10
    while time.time() - start_time < 600 and attempt < max_attempts:
        time.sleep(30)
        try:
            status_response = requests.get(status_url, headers=headers)
            status_response.raise_for_status()
            status_data = status_response.json()
            stage = status_data.get("stage", "")
            logging.info(f"空间{space_name}当前状态: {stage}")
            if stage == "RUNNING":
                duration = time.time() - start_time
                logging.info(f"✅空间{space_name}已成功重新构建, 耗时: {duration:.2f}秒!")
                return True, duration
            elif "ERROR" in stage:
                duration = time.time() - start_time
                logging.error(f"❌空间{space_name}构建失败, 耗时: {duration:.2f}秒: {stage}")
                return False, duration
        except requests.exceptions.RequestException as e:
            duration = time.time() - start_time
            logging.error(f"❌空间{space_name}状态请求失败, 耗时: {duration:.2f}秒: {e}")
            return False, duration
        except Exception as e:
            duration = time.time() - start_time
            logging.exception(f"❌空间{space_name}发生未知错误, 耗时: {duration:.2f}秒: {e}")
            return False, duration
        attempt += 1

    duration = time.time() - start_time
    logging.warning(f"⚠️空间{space_name}构建状态未知 (超时或达到最大尝试次数), 耗时: {duration:.2f}秒")
    return False, duration

def generate_html_report(results, report_file="index.html"):
    current_time_utc = datetime.datetime.now(pytz.utc)
    current_time_cst = current_time_utc.astimezone(pytz.timezone('Asia/Shanghai'))
    formatted_time = current_time_cst.strftime('%Y-%m-%d %H:%M:%S %Z%z')
    current_date = formatted_time.split(" ")[0]

    if os.path.exists(report_file):
        with open(report_file, "r", encoding="utf-8") as f:
            html_content = f.read()
    else:
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Hugging Face 空间状态</title>
            <style>
                body { font-family: sans-serif; }
                table { border-collapse: collapse; width: 80%; margin: 20px auto; }
                th, td { border: 1px solid black; padding: 8px; text-align: left; }
                th { background-color: #f2f2f2; }
                .success { color: green; }
                .failure { color: red; }
            </style>
        </head>
        <body>
            <h1>Hugging Face 空间状态</h1>
            <div id="content"></div>
        </body>
        </html>
        """

    existing_data = OrderedDict()
    if "<table" in html_content:
        table_start = html_content.find("<table")
        table_end = html_content.find("</table>", table_start) + 8
        table_html = html_content[table_start:table_end]

        rows = table_html.split("<tr")[2:]
        for row in rows:
            if "</tr>" in row:
                cols = row.split("<td")
                if len(cols) >= 4:
                    timestamp = cols[1].split("</td>")[0].strip()
                    if timestamp.startswith(current_date):
                        existing_data[timestamp] = {}
                        for i, space in enumerate(space_list):
                            status_html = cols[i + 2].split("</td>")[0].strip()
                            duration_html = cols[i + 3].split("</td>")[0].strip()

                            if '<span class="success">✅</span>' in status_html:
                                existing_data[timestamp][space] = {"status": True, "duration": duration_html}
                            else:
                                existing_data[timestamp][space] = {"status": False, "duration": duration_html}

    existing_data[formatted_time] = {}
    for r in results:
        if r["result"] is not None:
            existing_data[formatted_time][r['space']] = {"status": r['result'], "duration": f"{r['duration']:.2f}秒"}
        else:
            existing_data[formatted_time][r['space']] = {"status": False, "duration": f"{r['duration']:.2f}秒"}

    table_html = "<table>"
    table_html += "<thead><tr><th>执行时间 (CST)</th>"
    for space in space_list:
        table_html += f"<th>{space}</th>"
    table_html += "</tr></thead><tbody>"

    for timestamp, space_results in existing_data.items():
        table_html += "<tr>"
        table_html += f"<td>{timestamp}</td>"
        for space in space_list:
            result = space_results.get(space)
            if result:
                status = result["status"]
                duration = result["duration"]
                if status:
                    table_html += f'<td><span class="success">✅</span></td><td>{duration}</td>'
                else:
                    table_html += f'<td><span class="failure">❌</span></td><td>{duration}</td>'
            else:
                table_html += f'<td><span class="failure">❌</span></td><td>N/A</td>'
        table_html += "</tr>"

    table_html += "</tbody></table>"

    if "<table" in html_content:
        content_start = html_content.find("<table")
        content_end = html_content.find("</table>", content_start) + 8
        html_content = html_content[:content_start] + table_html + html_content[content_end:]
    else:
        content_div_start = html_content.find('<div id="content">')
        content_div_end = html_content.find('</div>', content_div_start) + 6
        html_content = html_content[:content_div_start] + '<div id="content">' + table_html + html_content[content_div_end:]

    with open(report_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    logging.info(f"HTML 报告已生成: {report_file}")
    
    return formatted_time

def update_readme(formatted_time):
    readme_file = "README.md"
    current_date = formatted_time.split(" ")[0]

    github_repo = os.environ.get("GITHUB_REPOSITORY")
    if github_repo:
        commit_sha = os.environ.get("GITHUB_SHA")
        index_history_link = f"[{current_date}](https://github.com/{github_repo}/commits/{commit_sha}/index.html)"
    else:
        index_history_link = current_date
        logging.warning("未找到 GITHUB_REPOSITORY 环境变量, 无法生成历史链接。")

    if os.path.exists(readme_file):
        with open(readme_file, "r", encoding="utf-8") as f:
            readme_content = f.read()
    else:
        readme_content = "# Hugging Face 空间状态历史记录\n\n| 日期 | 状态 |\n|---|---|\n"

    readme_lines = readme_content.split("\n")
    existing_dates = []
    for line in readme_lines[2:]:
        if "|" in line:
            cols = line.split("|")
            if len(cols) >= 3:
                existing_dates.append(cols[1].strip())

    if current_date not in existing_dates:
      updated_readme_content = readme_content
      if "未找到 GITHUB_REPOSITORY 环境变量" not in readme_content:
          updated_readme_content += f"| {index_history_link} |  |\n"

      with open(readme_file, "w", encoding="utf-8") as f:
          f.write(updated_readme_content)
      logging.info(f"README.md 已更新，添加了 {current_date} 的记录。")
    else:
      logging.info(f"README.md 已包含 {current_date} 的记录, 无需更新。")

start_time = time.time()
results = []
for space in space_list:
    if time.time() - start_time > global_timeout_seconds:
        logging.warning(f"⚠️全局超时，剩余空间未处理")
        break

    status, duration = check_space_with_browser_emulation(space)
    if not status:
        rebuild_result, rebuild_duration = rebuild_space(space)
        results.append({"space": space, "result": rebuild_result, "duration": rebuild_duration})
    else:
        results.append({"space": space, "result": status, "duration": duration})

formatted_time = generate_html_report(results)

update_readme(formatted_time)

exit_code = 1 if any(r['result'] is False for r in results) else 0
with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
    print(f"exit_code={exit_code}", file=f)

if exit_code != 0:
    exit(1)
else:
    exit(0)
