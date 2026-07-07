"""Interactive hover-able + searchable UMAP of the text embedding space (Week 3.5).

Reuses the saved 2-D layout (umap_2d.parquet) — no re-fit — and renders a
self-contained HTML scatter you open in any browser:
  - SEARCH box: type a course title; matches are highlighted on the map, listed,
    and "zoom to matches" frames them.
  - hover any point -> course title + department + course_id
  - zoom / pan into the dense mixing zone the static PNG smears together
  - click a college (or dept) in the legend to toggle it on/off

  data/embeddings/<model-slug>/umap_2d.parquet
    -> data/embeddings/<model-slug>/umap_2d.html   (open in a browser, no Python needed)

The search box is a small hand-written HTML+JS shell wrapped around the Plotly
figure (Plotly has no native search). Color by college (default) or department.

Usage:
  PYTHONPATH=src ~/latent-campus-venv/bin/python scripts/umap_interactive.py
  PYTHONPATH=src ~/latent-campus-venv/bin/python scripts/umap_interactive.py --color-by dept
"""
import argparse
import json

import numpy as np
import plotly.graph_objects as go
import polars as pl

from latent_campus.common.config import DATA_DIR

DEFAULT_MODEL_SLUG = "bge-large-en-v1.5"

# Best-effort CMU dept-code -> college (verify against your knowledge of CMU).
COLLEGE = {
    "48": "CFA", "51": "CFA", "54": "CFA", "57": "CFA", "60": "CFA", "62": "CFA",
    "06": "CIT", "12": "CIT", "18": "CIT", "19": "CIT", "24": "CIT", "27": "CIT", "42": "CIT",
    "03": "MCS", "09": "MCS", "21": "MCS", "33": "MCS", "38": "MCS", "86": "MCS",
    "02": "SCS", "05": "SCS", "07": "SCS", "08": "SCS", "10": "SCS", "11": "SCS",
    "15": "SCS", "16": "SCS", "17": "SCS",
    "36": "Dietrich", "65": "Dietrich", "66": "Dietrich", "73": "Dietrich", "76": "Dietrich",
    "79": "Dietrich", "80": "Dietrich", "82": "Dietrich", "84": "Dietrich", "85": "Dietrich",
    "88": "Dietrich",
    "45": "Tepper", "46": "Tepper", "47": "Tepper", "70": "Tepper",
    "67": "Heinz", "90": "Heinz", "91": "Heinz", "92": "Heinz", "93": "Heinz",
    "94": "Heinz", "95": "Heinz",
    "98": "StuCo",
}
COLLEGE_COLORS = {
    "CFA": "#e41a1c", "CIT": "#377eb8", "MCS": "#4daf4a", "SCS": "#984ea3",
    "Dietrich": "#ff7f00", "Tepper": "#a65628", "Heinz": "#f781bf",
    "StuCo": "#888888", "Other": "#cccccc",
}

# Hand-written shell: search box + match-highlighting JS wrapped around the plot.
PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Latent Campus — UMAP</title>
<style>
 body{font-family:-apple-system,sans-serif;margin:0}
 #bar{padding:10px 14px;background:#f4f4f6;border-bottom:1px solid #ddd;
      position:sticky;top:0;z-index:9}
 #q{font-size:15px;padding:5px 8px;width:340px;border:1px solid #bbb;border-radius:5px}
 #bar button{font-size:13px;padding:5px 10px;margin-left:6px;cursor:pointer}
 #count{margin-left:10px;color:#555;font-size:13px}
 #res{margin-top:8px;font-size:12px;color:#333;max-height:120px;overflow:auto;line-height:1.5}
 #res .r{cursor:pointer;padding-right:14px;white-space:nowrap;display:inline-block}
 #res .r:hover{text-decoration:underline}
</style></head><body>
<div id="bar">
  🔍 <input id="q" autocomplete="off"
       placeholder="search course title — e.g. machine learning, ethics, painting">
  <button id="zoom">zoom to matches</button>
  <button id="reset">reset view</button>
  <span id="count"></span>
  <div id="res"></div>
</div>
__FIG__
<script>
const COURSES = __COURSES__, MIDX = __MIDX__;
const X0=__X0__, X1=__X1__, Y0=__Y0__, Y1=__Y1__;
const gd = document.getElementById('umap');
const q=document.getElementById('q'), count=document.getElementById('count'),
      res=document.getElementById('res');
let last=[];
function highlight(list){
  Plotly.restyle(gd, {x:[list.map(c=>c.x)], y:[list.map(c=>c.y)],
    text:[list.map(c=>c.id+' — '+c.title)]}, [MIDX]);
}
function update(){
  const s=q.value.trim().toLowerCase();
  last = s ? COURSES.filter(c=>c.title.toLowerCase().includes(s)) : [];
  highlight(last);
  count.textContent = s ? (last.length+' match'+(last.length===1?'':'es')) : '';
  res.innerHTML = last.slice(0,50).map((c,i)=>
    '<span class="r" data-i="'+i+'">['+c.dept+'-'+c.id+'] '+c.title+'</span>').join('');
  res.querySelectorAll('.r').forEach(el=>el.onclick=()=>{
    const c=last[+el.dataset.i], p=1.5;
    Plotly.relayout(gd,{'xaxis.range':[c.x-p,c.x+p],'yaxis.range':[c.y-p,c.y+p]});
  });
}
q.addEventListener('input', update);
document.getElementById('zoom').onclick=()=>{
  if(!last.length) return;
  const xs=last.map(c=>c.x), ys=last.map(c=>c.y), p=2;
  Plotly.relayout(gd,{'xaxis.range':[Math.min(...xs)-p,Math.max(...xs)+p],
    'yaxis.range':[Math.min(...ys)-p,Math.max(...ys)+p]});
};
document.getElementById('reset').onclick=()=>
  Plotly.relayout(gd,{'xaxis.range':[X0,X1],'yaxis.range':[Y0,Y1]});
</script></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-slug", default=DEFAULT_MODEL_SLUG)
    ap.add_argument("--color-by", choices=("college", "dept"), default="college")
    args = ap.parse_args()

    emb_dir = DATA_DIR / "embeddings" / args.model_slug
    df = pl.read_parquet(emb_dir / "umap_2d.parquet").with_columns(
        pl.col("dept_code").replace_strict(COLLEGE, default="Other").alias("college")
    )

    group_col = "college" if args.color_by == "college" else "dept_code"
    sizes = df.group_by(group_col).len().sort("len", descending=True)
    groups = [g for g in sizes[group_col].to_list() if g != "Other"]
    if "Other" in sizes[group_col].to_list():
        groups = ["Other", *groups]

    fig = go.Figure()
    for g in groups:
        sub = df.filter(pl.col(group_col) == g)
        color = COLLEGE_COLORS.get(g) if args.color_by == "college" else None
        custom = np.stack(
            [sub["course_id"].to_list(), sub["dept_code"].to_list(), sub["title"].to_list()],
            axis=-1,
        )
        fig.add_trace(
            go.Scattergl(
                x=sub["x"].to_numpy(),
                y=sub["y"].to_numpy(),
                mode="markers",
                name=f"{g} ({sub.height})",
                marker=dict(size=5, color=color, opacity=0.5 if g == "Other" else 0.8),
                customdata=custom,
                hovertemplate=(
                    "<b>%{customdata[2]}</b><br>"
                    "dept %{customdata[1]} · %{customdata[0]}<extra></extra>"
                ),
            )
        )

    # Search-highlight trace (last): big hollow black rings over matched courses.
    fig.add_trace(
        go.Scattergl(
            x=[], y=[], mode="markers", name="🔍 search match",
            marker=dict(size=15, color="rgba(0,0,0,0)", line=dict(color="black", width=2.5)),
            text=[], hovertemplate="%{text}<extra></extra>",
        )
    )
    match_idx = len(fig.data) - 1

    xy = df.select("x", "y").to_numpy()
    xlo, xhi = np.percentile(xy[:, 0], [1, 99])
    ylo, yhi = np.percentile(xy[:, 1], [1, 99])
    mx, my = 0.05 * (xhi - xlo), 0.05 * (yhi - ylo)
    x0, x1, y0, y1 = xlo - mx, xhi + mx, ylo - my, yhi + my
    fig.update_layout(
        title=(
            f"Latent Campus — UMAP of {df.height} course-text embeddings "
            f"(colored by {args.color_by})"
        ),
        xaxis=dict(range=[x0, x1], showticklabels=False, title=None),
        yaxis=dict(range=[y0, y1], showticklabels=False, title=None),
        legend=dict(title=args.color_by, itemsizing="constant"),
        plot_bgcolor="white",
        height=820,
    )

    fig_div = fig.to_html(full_html=False, include_plotlyjs=True, div_id="umap")
    courses = [
        {"id": cid, "dept": dept, "title": title, "x": round(float(x), 3), "y": round(float(y), 3)}
        for cid, dept, title, x, y in df.select(
            "course_id", "dept_code", "title", "x", "y"
        ).iter_rows()
    ]
    page = (
        PAGE.replace("__FIG__", fig_div)
        .replace("__COURSES__", json.dumps(courses))
        .replace("__MIDX__", str(match_idx))
        .replace("__X0__", f"{x0:.3f}").replace("__X1__", f"{x1:.3f}")
        .replace("__Y0__", f"{y0:.3f}").replace("__Y1__", f"{y1:.3f}")
    )
    out = emb_dir / "umap_2d.html"
    out.write_text(page)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB) — open in a browser; search box up top")


if __name__ == "__main__":
    main()
