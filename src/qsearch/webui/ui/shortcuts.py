"""键盘桥接。

标注吞吐量取决于键盘能否完成全部操作 —— 标注员一小时要过几百道题，
每次都摸鼠标是不可接受的。

原实现（postMessage 到 streamlit:setComponentValue）走不通：
components.v1.html 是隔离 iframe，那是双向自定义组件的协议，纯 HTML 组件
没有。任务 3.2 实测确认可行的路径是：iframe 内的 JS 访问
window.parent.document，按 Streamlit 为 st.button(key=...) 生成的
.st-key-<key> 类定位并 .click()，Streamlit 的既有事件通路随即接管。

焦点分两层（design.md D7）：

    视觉焦点   方向键移动   JS 在 parent DOM 上改 CSS 类   零往返
    逻辑焦点   标注时读取   JS 点击对应卡片的决策按钮       一轮往返

方向键若走服务端往返，每次移动约 3 秒（任务 3.3 实测的 rerun 地板），
卡片导航不可用。服务端不需要知道焦点在哪，只需要知道哪张卡被标注了。
"""

from __future__ import annotations

import json

import streamlit.components.v1 as components

FOCUS_CLASS = "qs-card--focused"

# 横向结果轨道只接管左右键；上下键保留给页面纵向滚动。
KEY_HINTS = [
    ("← / →", "移动结果焦点"),
    ("1", "命中"),
    ("0", "未命中"),
    ("S", "跳过"),
    ("?", "本面板"),
]


def render_keyboard_bridge(
    *,
    nav_map: list[dict[str, int]],
    card_keys: list[str],
    decision_keys: dict[str, list[str]],
    help_key: str,
    focus_mode: bool,
) -> None:
    """注入键盘桥接。

    导航表由 Python 预计算（grid_nav.nav_map）后传入，JS 只做查表 ——
    在 JS 里重写一遍网格数学意味着两份实现会漂移，而其中只有一份被测到。

    Args:
        nav_map: 每个索引在四方向上的目标索引
        card_keys: 各卡片容器的 key，与索引对齐
        decision_keys: ``{"hit": [...], "miss": [...], "skip": [...]}``，与索引对齐
        help_key: 快捷键速查按钮的 key
        focus_mode: 是否处于专注模式（决定 body 上的 data-qs-focus）
    """
    payload = json.dumps({
        "navMap": nav_map,
        "cardKeys": card_keys,
        "decisionKeys": decision_keys,
        "helpKey": help_key,
        "focusClass": FOCUS_CLASS,
        "focusMode": "1" if focus_mode else "0",
    })

    components.iframe(_BRIDGE_JS.replace("__PAYLOAD__", payload), height=0)


_BRIDGE_JS = """
<script>
(function () {
  const P = __PAYLOAD__;

  let pd, W;
  try { W = window.parent; pd = W.document; } catch (e) { return; }

  // 专注模式：CSS 靠 body[data-qs-focus="1"] 收侧栏、压边距、放开宽度上限
  if (P.focusMode === "1") pd.body.setAttribute("data-qs-focus", "1");
  else pd.body.removeAttribute("data-qs-focus");

  if (typeof W.__qsFocus !== "number") W.__qsFocus = 0;
  const last = P.navMap.length - 1;
  W.__qsFocus = Math.max(0, Math.min(W.__qsFocus, last < 0 ? 0 : last));

  const container = (key) => (key ? pd.querySelector("." + "st-key-" + key) : null);

  function paint() {
    P.cardKeys.forEach((k, i) => {
      const el = container(k);
      if (el) el.classList.toggle(P.focusClass, i === W.__qsFocus);
    });
  }

  function reveal(i) {
    const el = container(P.cardKeys[i]);
    if (el && el.scrollIntoView) {
      el.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }

  function press(key) {
    const el = container(key);
    const btn = el ? el.querySelector("button") : null;
    if (!btn) return false;
    // rerun 期间加锁，避免连续按键在往返中丢事件或错标
    W.__qsLock = true;
    btn.click();
    return true;
  }

  const DIRS = { ArrowLeft: "left", ArrowRight: "right" };

  function onKey(e) {
    const t = e.target;
    // 在输入区域内不触发标注 —— 否则填备注时打「1」会误标
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    if (W.__qsLock) return;

    const dir = DIRS[e.key];
    if (dir) {
      e.preventDefault();
      const entry = P.navMap[W.__qsFocus];
      if (entry && typeof entry[dir] === "number") {
        W.__qsFocus = entry[dir];
        paint();
        reveal(W.__qsFocus);
      }
      return;
    }

    const i = W.__qsFocus;
    if (e.key === "1") { e.preventDefault(); press((P.decisionKeys.hit || [])[i]); return; }
    if (e.key === "0") { e.preventDefault(); press((P.decisionKeys.miss || [])[i]); return; }
    if (e.key === "s" || e.key === "S") { e.preventDefault(); press((P.decisionKeys.skip || [])[i]); return; }
    if (e.key === "?") { e.preventDefault(); press(P.helpKey); return; }
  }

  // 每次 rerun 都会重新执行本脚本。先摘掉旧监听，否则监听器会累积，
  // 一次按键触发 N 次。摘除时的 capture 标志必须与注册时一致。
  if (W.__qsKeyHandler) pd.removeEventListener("keydown", W.__qsKeyHandler, true);
  W.__qsKeyHandler = onKey;

  // 捕获阶段注册（第三参数 true），而非冒泡阶段。
  //
  // Streamlit 的标签条是 [role="tablist"]，它自己处理左右方向键用于切换
  // 标签，并调用 stopPropagation()。冒泡阶段 document 上的监听器排在
  // 后代元素之后，于是焦点停留在标签按钮上时，左右键被标签条吃掉 ——
  // 上下键能动、左右键不能，实测确认过这个不对称。
  //
  // 捕获阶段自 document 向下传播，先于任何后代处理器执行。
  pd.addEventListener("keydown", onKey, true);

  // 本脚本重新执行意味着 rerun 已完成，解锁。
  W.__qsLock = false;
  paint();
})();
</script>
"""
