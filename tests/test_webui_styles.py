"""样式表加载与设计令牌纪律的测试。

这里的断言不只覆盖 styles.py 的读取逻辑，也把几条设计纪律固定成回归测试：
令牌隔离、选择器稳定性、阴影只用于浮层、半透明只用于浮层。这些纪律靠人眼
审查容易随时间松掉，写成测试才不会。
"""

import re
from pathlib import Path

import pytest

from qsearch.webui import styles_audit
from qsearch.webui.ui import styles


def _read(name: str) -> str:
    return (styles.STYLES_DIR / name).read_text(encoding="utf-8")


class TestStylesheetLoading:
    """样式表的读取与拼接。"""

    def test_all_declared_stylesheets_exist(self):
        """声明于 STYLESHEETS 的每个文件都必须存在于磁盘。"""
        missing = [n for n in styles.STYLESHEETS if not (styles.STYLES_DIR / n).is_file()]
        assert missing == [], f"声明但不存在的样式表：{missing}"

    def test_tokens_load_first(self):
        """tokens.css 必须最先加载 —— 后续各表通过 var(--*) 引用其声明。"""
        assert styles.STYLESHEETS[0] == "tokens.css"

    def test_glass_loads_last(self):
        """glass.css 必须最后加载，以覆盖组件层的浮层默认外观。"""
        assert styles.STYLESHEETS[-1] == "glass.css"

    def test_load_css_concatenates_in_declared_order(self):
        """拼接结果中各段的出现顺序与 STYLESHEETS 一致。"""
        css = styles.load_css()
        positions = [css.index(f"===== {name} =====") for name in styles.STYLESHEETS]
        assert positions == sorted(positions)

    def test_load_css_is_non_empty(self):
        css = styles.load_css()
        assert len(css) > 1000

    def test_missing_stylesheet_raises_rather_than_injecting_empty(self, monkeypatch):
        """文件缺失时报错，而非静默注入空样式。

        静默降级会让界面看起来像是坏了，而不像是一次明确的失败 —— 那种
        故障要靠肉眼在四个页面上找，成本远高于一次启动期异常。
        """
        monkeypatch.setattr(styles, "STYLESHEETS", ("tokens.css", "does-not-exist.css"))

        with pytest.raises(styles.StylesheetError) as exc:
            styles.load_css()

        assert "does-not-exist.css" in str(exc.value)

    def test_unreadable_stylesheet_raises(self, monkeypatch):
        """路径指向目录（不可读为文本）时同样报错。"""
        monkeypatch.setattr(styles, "STYLESHEETS", ("tokens.css", ""))

        with pytest.raises(styles.StylesheetError):
            styles.load_css()


class TestTokenIsolation:
    """令牌与组件规则的分离。"""

    def test_tokens_declares_only_root(self):
        """tokens.css 只含 :root 声明块，不含组件规则。"""
        css = _read("tokens.css")
        stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
        selectors = re.findall(r"([^{}]+)\{", stripped)
        assert [s.strip() for s in selectors] == [":root"]

    @pytest.mark.parametrize(
        "name", ["components.css", "chips.css", "table.css", "workbench.css"]
    )
    def test_component_sheets_have_no_literal_colors(self, name):
        """组件表内不得出现字面色值 —— 颜色只在 tokens.css 声明。

        字面色值散落各处会让「改一处颜色」变成「grep 全仓库」，也让
        深色/亮色的一致性无法保证。
        """
        css = _read(name)
        stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
        literals = re.findall(r"#[0-9a-fA-F]{3,8}\b|\brgba?\([^)]*\)", stripped)
        assert literals == [], f"{name} 中的字面色值应改为 var(--*)：{literals}"


class TestSelectorStability:
    """选择器纪律（D4）—— 样式不得因 Streamlit 补丁升级而破损。"""

    @pytest.mark.parametrize("name", styles.STYLESHEETS)
    def test_no_hashed_class_names(self, name):
        """不得依赖 Streamlit 生成的哈希类名（如 .css-1r6slb0）。"""
        css = _read(name)
        hashed = re.findall(r"\.css-[a-z0-9]+", css)
        assert hashed == [], f"{name} 中的哈希类名会随版本失效：{hashed}"

    @pytest.mark.parametrize("name", styles.STYLESHEETS)
    def test_no_data_baseweb_selectors(self, name):
        """不得依赖 data-baseweb —— 该属性在 Streamlit 1.63 中已从 DOM 移除。"""
        css = re.sub(r"/\*.*?\*/", "", _read(name), flags=re.DOTALL)
        assert "data-baseweb" not in css, f"{name} 使用了已失效的 data-baseweb"


class TestFlatDiscipline:
    """Flat 2.0 与 Material 的调和纪律（D1）。"""

    def test_no_gradients_anywhere(self):
        """装饰性渐变一律移除。"""
        for name in styles.STYLESHEETS:
            css = re.sub(r"/\*.*?\*/", "", _read(name), flags=re.DOTALL)
            assert "linear-gradient" not in css, f"{name} 仍含渐变"
            assert "radial-gradient" not in css, f"{name} 仍含渐变"

    def test_no_hover_translate(self):
        """悬停不得产生位移 —— 长时间盯屏时的微动干扰。"""
        for name in styles.STYLESHEETS:
            css = re.sub(r"/\*.*?\*/", "", _read(name), flags=re.DOTALL)
            assert "translateY" not in css, f"{name} 仍含悬停位移"


class TestAnnotationNavigationLayout:
    """固定 Query 导航的样式契约。"""

    def test_query_navigation_is_sticky_and_horizontally_scrollable(self):
        css = _read("workbench.css")
        assert 'st-key-qs_query_navigation' in css
        assert "position: sticky" in css
        assert "overflow-x: auto" in css
        assert "flex-wrap: nowrap" in css

    def test_query_navigation_has_four_state_colors_and_current_outline(self):
        css = _read("workbench.css")
        for state, token in (
            ("unlabeled", "--task-pending"),
            ("partial", "--task-running"),
            ("completed", "--task-done"),
            ("no_candidates", "--task-failed"),
        ):
            assert f'_{state}_' in css
            assert f"var({token})" in css
        assert 'class*="_selected"' in css
        assert "outline: 2px solid var(--focus)" in css

    def test_candidate_cards_use_a_wide_single_row_scroll_track(self):
        css = _read("workbench.css")
        assert "st-key-qscandidate_strip" in css
        assert "flex-wrap: nowrap" in css
        assert "overflow-x: auto" in css
        assert "min-width: 360px" in css
        assert "flex: 0 0 360px" in css


class TestFlatShadowDiscipline:
    """阴影仅用于浮层或焦点表达。"""

    def test_shadows_only_on_overlays(self):
        """box-shadow 只允许出现在浮层规则中。

        非浮层元素的层级由 surface 明度差表达，而非阴影堆叠。
        焦点环用的 box-shadow 例外 —— 那是可访问性指示，不是深度表达。
        """
        overlay_tokens = (
            "toast", "popover", "dialog", "menu", "tooltip",
            "focus", "shadow-overlay", "shadow-modal",
        )
        for name in ("base.css", "components.css", "workbench.css"):
            css = re.sub(r"/\*.*?\*/", "", _read(name), flags=re.DOTALL)
            for block in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
                selector, body = block
                if "box-shadow" not in body or "box-shadow: none" in body:
                    continue
                context = (selector + body).lower()
                assert any(t in context for t in overlay_tokens), (
                    f"{name} 在非浮层规则上使用了阴影：{selector.strip()}"
                )


class TestGlassScope:
    """半透明的准入范围。"""

    def test_backdrop_filter_only_in_glass_sheet(self):
        """backdrop-filter 只允许出现在 glass.css。"""
        for name in styles.STYLESHEETS:
            if name == "glass.css":
                continue
            css = _read(name)
            assert "backdrop-filter" not in css, f"{name} 不应使用 backdrop-filter"

    def test_glass_does_not_target_non_overlay_elements(self):
        """glass.css 不得覆盖卡片、表格、侧栏等文档流内元素。"""
        css = re.sub(r"/\*.*?\*/", "", _read("glass.css"), flags=re.DOTALL)
        forbidden = ("stSidebar", "stDataFrame", "stTable", "stMetric", "qs-card")
        hit = [f for f in forbidden if f in css]
        assert hit == [], f"glass.css 触及了非浮层元素：{hit}"

    def test_glass_has_no_backdrop_filter_fallback(self):
        """必须为不支持 backdrop-filter 的环境提供不透明降级。"""
        css = _read("glass.css")
        assert "@supports not (backdrop-filter" in css


class TestContrast:
    """令牌对比度核算。

    这些断言算得出偏差，而肉眼看不出：--text-3 原值 #6B7580 压在 surface-2
    上仅 4.31:1，低于 4.5 下限，而它正用在显示文件路径的 caption 上。
    """

    def test_no_combination_below_threshold(self):
        """全部核算组合均达标。"""
        bad = styles_audit.failures()
        detail = "\n".join(
            f"  --{r['fg']} ({r['fg_value']}) on --{r['bg']} ({r['bg_value']})"
            f" = {r['ratio']} < {r['threshold']}"
            for r in bad
        )
        assert bad == [], f"以下组合低于对比度下限：\n{detail}"

    def test_audit_covers_all_text_levels(self):
        """三级文字令牌都被核算到 —— 漏掉一级等于没测。"""
        rows = styles_audit.audit()
        covered = {r["fg"] for r in rows}
        assert {"text-1", "text-2", "text-3"} <= covered

    def test_audit_covers_decision_and_info_registers(self):
        """决策徽章与信息 chip 两组都被核算到。"""
        groups = {r["group"] for r in styles_audit.audit()}
        assert {"文字/表面", "chip 文字", "chip 描边", "badge 文字", "焦点环"} <= groups

    def test_border_pairs_use_non_text_threshold(self):
        """描边按 3:1 核算，不按 4.5。

        规格的 4.5 限定于「承载信息的文本」；描边是非文本 UI 组件，
        WCAG 1.4.11 对其取 3:1。把描边并入文本阈值会制造假失败 ——
        task-cancelled 作描边时为 3.71，达标却会被误判。
        """
        rows = styles_audit.audit()
        border_rows = [r for r in rows if r["group"] in ("chip 描边", "焦点环")]
        assert border_rows, "描边组为空 —— 核算漏了这一类"
        assert all(r["threshold"] == styles_audit.MIN_NON_TEXT for r in border_rows)

        text_rows = [r for r in rows if "文字" in r["group"]]
        assert all(r["threshold"] == styles_audit.MIN_BODY for r in text_rows)

    def test_text_hierarchy_stays_distinguishable(self):
        """三级文字之间保持可辨的明度差。

        把 text-3 提亮到达标时，若一路提到与 text-2 无异，三级层级就塌成
        两级 —— 达标了但失去了层级表达能力。
        """
        t = styles_audit.parse_tokens()
        lum = lambda name: styles_audit.relative_luminance(
            styles_audit.hex_to_rgb(t[name])
        )
        l1, l2, l3 = lum("text-1"), lum("text-2"), lum("text-3")
        assert l1 > l2 > l3, f"明度未单调递减：{l1:.4f} / {l2:.4f} / {l3:.4f}"
        assert l2 - l3 > 0.02, f"text-2 与 text-3 明度差过小：{l2 - l3:.4f}"

    def test_surface_ladder_is_monotonic(self):
        """五级表面的明度必须单调递增。

        深色模式下层级由明度承担（D1），若某两级顺序颠倒或相等，
        「卡片浮于面板之上」这件事就无法被看出来。
        """
        t = styles_audit.parse_tokens()
        lums = [
            styles_audit.relative_luminance(styles_audit.hex_to_rgb(t[f"surface-{i}"]))
            for i in range(5)
        ]
        assert lums == sorted(lums), f"表面明度非单调：{[round(x, 4) for x in lums]}"
        for i in range(4):
            assert lums[i + 1] > lums[i], f"surface-{i} 与 surface-{i+1} 明度相同"

    def test_tokens_css_and_config_toml_agree(self):
        """tokens.css 与 config.toml 的同名值必须一致。

        二者是同一套值的两种表达（组件层与兜底层）。漂移会让未被 CSS
        覆盖到的内建组件落在与自定义规则不同的色系上 —— 那正是当前
        深色模式破损的形态。
        """
        import tomllib

        cfg_path = Path(__file__).parent.parent / ".streamlit" / "config.toml"
        cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))["theme"]
        t = styles_audit.parse_tokens()

        pairs = [
            ("backgroundColor", "surface-0"),
            ("secondaryBackgroundColor", "surface-1"),
            ("textColor", "text-1"),
            ("primaryColor", "focus"),
            ("borderColor", "border-hair-solid"),
            ("codeBackgroundColor", "surface-2"),
        ]
        for cfg_key, token in pairs:
            assert cfg[cfg_key].lower() == t[token].lower(), (
                f"config.toml 的 {cfg_key}={cfg[cfg_key]} "
                f"与 tokens.css 的 --{token}={t[token]} 不一致"
            )
