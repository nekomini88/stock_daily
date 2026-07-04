import json
import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

BASE = Path(__file__).parent

env = Environment(
    loader=FileSystemLoader(BASE / "templates"),
    autoescape=False
)
today = datetime.today().strftime("%Y-%m-%d")
with open(f"market_data_{today}.json","r",encoding="utf8") as f:
    data=json.load(f)

html_tpl=env.get_template("report.html.j2")
txt_tpl=env.get_template("report.txt.j2")

html=html_tpl.render(data=data)
txt=txt_tpl.render(data=data)

Path("output").mkdir(exist_ok=True)

(Path("output")/"report.html").write_text(html,encoding="utf8")
(Path("output")/"report.txt").write_text(txt,encoding="utf8")
