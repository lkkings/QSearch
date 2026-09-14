"""数据库管理页面 - 重构版本。

任务 8.1-8.4：
- 列内容居中（除名称列外）
- 行操作收敛为三个跳转按钮
- 跳转带入数据集参数
- 删除移至详情页
"""

import streamlit as st
import yaml
from pathlib import Path

from qsearch.webui.database_manager import DatabaseManager, DatabaseManagementError
from qsearch.webui.ui import components
from qsearch.webui.workspace_state import (
    ANNOTATION_VIEW,
    DETAILS_VIEW,
    SEARCH_VIEW,
    activate_workspace_view,
)

# 列宽：名称占大头，其余压紧
_COL_WIDTHS = [3, 1.2, 1.6, 1.2, 2.4]


def render_database_management_page(databases_root: Path):
    """渲染数据库管理页面。

    Args:
        databases_root: 数据库根目录
    """
    st.header(":material/folder: 数据库管理")

    db_manager = DatabaseManager(databases_root)

    tab1, tab2 = st.tabs(
        [":material/list: 数据库列表", ":material/add_circle: 创建数据库"]
    )

    with tab1:
        render_database_list(db_manager)

    with tab2:
        render_create_database_form(db_manager)


def render_database_list(db_manager: DatabaseManager):
    """以紧凑表格呈现数据库列表。

    Args:
        db_manager: DatabaseManager 实例
    """
    # 入队结果展示
    build = st.session_state.pop('build_result', None)
    if build:
        kind, payload = build
        if kind == 'ok':
            name, task_id, workers = payload
            st.success(
                f"「{name}」的索引构建已入队（任务 {task_id[:8]}）。"
                "进度见「任务监控」。"
            )
        else:
            st.error(f"入队失败：{payload}")

    databases = db_manager.list_databases()

    if not databases:
        st.info("暂无数据库。请在「创建数据库」标签页中新建。")
        return

    st.caption(f"共 {len(databases)} 个数据库")

    # 表头（任务 8.1：名称列左对齐，其他列居中）
    head = st.columns(_COL_WIDTHS)
    headers = ["名称", "图像", "索引", "命中率", "操作"]
    for i, (col, text) in enumerate(zip(head, headers)):
        align = "left" if i == 0 else "center"
        col.markdown(
            f'<div class="qs-th" style="text-align: {align}">{text}</div>',
            unsafe_allow_html=True
        )

    for db in databases:
        name = db['name']
        stats = db.get('statistics', {})

        with st.container(key=f"qsrow_{name}"):
            cols = st.columns(_COL_WIDTHS)

            # 名称列（左对齐）
            with cols[0]:
                st.markdown(
                    f'<div class="qs-td qs-td--name">{name}'
                    f'<span class="qs-td-sub">{db["created_at"][:10]}</span></div>',
                    unsafe_allow_html=True,
                )

            # 图像数量（居中，任务 8.1）
            with cols[1]:
                st.markdown(
                    f'<div class="qs-td" style="text-align: center">{db["image_count"]:,}</div>',
                    unsafe_allow_html=True,
                )

            # 索引状态（居中，任务 8.1）
            with cols[2]:
                status_html = components.index_status(bool(db.get("index_built")))
                st.markdown(
                    f'<div class="qs-td" style="text-align: center">{status_html}</div>',
                    unsafe_allow_html=True,
                )

            # 命中率（居中，任务 8.1）
            with cols[3]:
                labeled = stats.get('labeled_candidates', 0)
                rate = f"{stats.get('hit_rate', 0.0):.1%}" if labeled else "—"
                st.markdown(
                    f'<div class="qs-td" style="text-align: center">{rate}</div>',
                    unsafe_allow_html=True,
                )

            # 操作列：只有三个跳转按钮（任务 8.2）
            with cols[4]:
                a1, a2, a3 = st.columns(3)

                # 详情按钮（任务 8.3）
                if a1.button("详情", key=f"detail_{name}", width="stretch"):
                    activate_workspace_view(
                        st.session_state, DETAILS_VIEW, database_name=name
                    )
                    st.rerun()

                # 搜索按钮（任务 8.3）
                if a2.button("搜索", key=f"search_{name}", width="stretch"):
                    activate_workspace_view(
                        st.session_state, SEARCH_VIEW, database_name=name
                    )
                    st.rerun()

                # 标注按钮（任务 8.3）
                if a3.button("标注", key=f"annotate_{name}", width="stretch"):
                    activate_workspace_view(
                        st.session_state, ANNOTATION_VIEW, database_name=name
                    )
                    st.rerun()

    # 建索引对话框（保留，但从列表中移除）
    if 'build_confirm' in st.session_state:
        build_index_dialog(db_manager, st.session_state['build_confirm'])


def render_create_database_form(db_manager: DatabaseManager):
    """渲染创建数据库表单。

    Args:
        db_manager: DatabaseManager 实例
    """
    st.subheader("创建新数据库")

    # 显示创建结果（任务 8.9, 8.10）
    create_result = st.session_state.pop('create_result', None)
    if create_result:
        status, message = create_result
        if status == 'success':
            st.success(message)
            st.info(":material/check_circle: 索引构建任务已自动入队，可前往主页「任务监控」标签查看进度")
        elif status == 'index_failed':
            st.warning(message)
            st.info(":material/lightbulb: 数据集已创建，但索引构建入队失败。可在详情页手动建立索引。")
        else:
            st.error(message)

    with st.form("create_database_form", clear_on_submit=False):
        # 使用 session_state 管理表单输入（任务 8.8）
        if 'form_name' not in st.session_state:
            st.session_state['form_name'] = ""
        if 'form_image_dir' not in st.session_state:
            st.session_state['form_image_dir'] = ""
        if 'form_num_workers' not in st.session_state:
            st.session_state['form_num_workers'] = None
        if 'form_num_gpus' not in st.session_state:
            st.session_state['form_num_gpus'] = 0

        # 基本信息
        st.markdown("#### 基本信息")
        name = st.text_input(
            "数据库名称",
            value=st.session_state['form_name'],
            help="只能包含字母、数字、下划线和连字符"
        )

        image_dir = st.text_input(
            "图像目录路径",
            value=st.session_state['form_image_dir'],
            help="包含图像文件的目录的绝对路径"
        )

        # 索引构建参数
        st.markdown("#### 索引构建参数")

        with st.expander("**计算资源配置**", expanded=True):
            col1, col2, col3 = st.columns(3)

            with col1:
                num_workers = st.number_input(
                    "CPU 工作进程数",
                    min_value=1,
                    max_value=32,
                    value=st.session_state['form_num_workers'] or 4,
                    help="并行提取特征的 CPU 进程数。建议设置为 CPU 核心数的 50%-75%。"
                )

            with col2:
                num_gpus = st.number_input(
                    "GPU 数量",
                    min_value=0,
                    max_value=8,
                    value=st.session_state['form_num_gpus'],
                    help="用于分布式特征提取的 GPU 数量。0 表示仅使用 CPU。设置 > 0 时将忽略 CPU 工作进程数。"
                )
            with col3:
                batch_size = st.number_input(
                    "批处理大小",
                    min_value=1,
                    max_value=512,
                    value=128,
                    step=16,
                    help="每批处理的图像数，增大提速但更占内存"
                )
        with st.expander("**文本特征提取**", expanded=True):
            st.caption("两步流程：OCR 提取文本 → 语义模型编码为向量")

            st.markdown("##### 1. OCR")
            ocr_col1, ocr_col2 = st.columns(2)
            with ocr_col1:
                ocr_languages = st.multiselect(
                    "识别语言",
                    options=["ch", "en"],
                    default=["ch", "en"],
                    help="ch 为中英混排模型，en 为纯英文模型。含 ch 时使用中文模型。"
                )
            with ocr_col2:
                ocr_confidence = st.slider(
                    "置信度阈值",
                    min_value=0.0,
                    max_value=1.0,
                    value=0.5,
                    step=0.05,
                    help="低于此置信度的文本行会被丢弃，不参与后续编码"
                )

            st.markdown("##### 2. 语义编码")
            enc_col1, enc_col2 = st.columns(2)
            with enc_col1:
                chinese_model = st.selectbox(
                    "中文模型",
                    options=[
                        "hfl/chinese-roberta-wwm-ext",
                        "hfl/chinese-bert-wwm-ext",
                        "shibing624/text2vec-base-chinese",
                    ],
                    index=0,
                    help="中文题目的句向量模型，输出 768 维"
                )
                english_model = st.selectbox(
                    "英文模型",
                    options=[
                        "sentence-transformers/all-mpnet-base-v2",
                        "sentence-transformers/all-MiniLM-L12-v2",
                        "bert-base-uncased",
                    ],
                    index=0,
                    help="英文题目的句向量模型"
                )
            with enc_col2:
                embedding_dim = st.number_input(
                    "向量维度",
                    min_value=128,
                    max_value=1024,
                    value=768,
                    step=128,
                    help="须与所选模型的隐层维度一致，同时决定 Faiss 索引维度"
                )
                max_length = st.number_input(
                    "最大 token 数",
                    min_value=64,
                    max_value=512,
                    value=512,
                    step=64,
                    help="超出部分会被截断。题目较短时降低可提速。"
                )

        with st.expander("**图像特征提取**", expanded=False):
            st.caption("感知哈希用于精确匹配，深度特征用于视觉相似度")

            st.markdown("##### 感知哈希")
            hash_col1, hash_col2 = st.columns(2)
            with hash_col1:
                enable_phash = st.checkbox(
                    "启用感知哈希",
                    value=True,
                    help="关闭后无法进行完全相同图的精确匹配"
                )
                phash_algorithm = st.selectbox(
                    "哈希算法",
                    options=["dHash", "pHash", "aHash"],
                    index=0,
                    help="dHash 对裁剪敏感度低；pHash 抗缩放更强；aHash 最快但最粗糙"
                )
            with hash_col2:
                hash_size = st.select_slider(
                    "哈希尺寸",
                    options=[8, 16, 32],
                    value=16,
                    help="位数为尺寸的平方。16 即 256 位，越大越精细也越严格。"
                )

            st.markdown("##### 深度特征")
            deep_col1, deep_col2 = st.columns(2)
            with deep_col1:
                enable_deep_features = st.checkbox(
                    "启用深度特征",
                    value=False,
                    help="需加载 CNN 模型，显著增加提取耗时"
                )
                cnn_model = st.selectbox(
                    "CNN 模型",
                    options=["efficientnet_b4", "resnet50"],
                    index=0,
                    help="efficientnet_b4 精度更高；resnet50 更快"
                )
            with deep_col2:
                cnn_output_dim = st.number_input(
                    "特征维度",
                    min_value=128,
                    max_value=2048,
                    value=512,
                    step=128,
                    help="CNN 特征向量的输出维度"
                )

        with st.expander("**Faiss 索引构建**", expanded=False):
            index_type = st.selectbox(
                "索引类型",
                options=["Flat", "IVFFlat", "IVFPQ", "HNSW"],
                index=0,
                help=(
                    "Flat：暴力检索，结果精确，规模大时慢；"
                    "IVFFlat：倒排聚类，速度与精度均衡；"
                    "IVFPQ：乘积量化压缩，省内存但有精度损失；"
                    "HNSW：图索引，查询快、内存占用高"
                )
            )

            # 各索引类型的参数互不相通，一次只展示相关项，避免填了不生效的值。
            if index_type in ("IVFFlat", "IVFPQ"):
                ivf_col1, ivf_col2 = st.columns(2)
                with ivf_col1:
                    nlist = st.number_input(
                        "聚类数 (nlist)",
                        min_value=1,
                        max_value=65536,
                        value=100,
                        help="倒排单元数量。经验值约为 sqrt(向量数)；数据量不足时会自动下调。"
                    )
                with ivf_col2:
                    nprobe = st.number_input(
                        "检索单元数 (nprobe)",
                        min_value=1,
                        max_value=4096,
                        value=10,
                        help="每次查询访问的单元数。越大越准越慢，须 ≤ nlist。"
                    )

                if index_type == "IVFPQ":
                    pq_col1, pq_col2 = st.columns(2)
                    with pq_col1:
                        m_pq = st.number_input(
                            "子向量数 (m)",
                            min_value=1,
                            max_value=128,
                            value=16,
                            help="须能整除向量维度。768 维可用 8/12/16/24/32/48/64。"
                        )
                    with pq_col2:
                        nbits = st.number_input(
                            "每子量化器位数 (nbits)",
                            min_value=4,
                            max_value=16,
                            value=8,
                            help="通常为 8。增大提升精度但索引变大。"
                        )

            elif index_type == "HNSW":
                hnsw_col1, hnsw_col2 = st.columns(2)
                with hnsw_col1:
                    hnsw_m = st.number_input(
                        "图连接数 (M)",
                        min_value=4,
                        max_value=128,
                        value=16,
                        help="每个节点的邻居数。越大召回越好，内存占用也越高。"
                    )
                    ef_construction = st.number_input(
                        "构建候选数 (efConstruction)",
                        min_value=8,
                        max_value=512,
                        value=40,
                        help="建图时的候选列表长度，影响索引质量与构建耗时"
                    )
                with hnsw_col2:
                    ef_search = st.number_input(
                        "查询候选数 (efSearch)",
                        min_value=8,
                        max_value=512,
                        value=32,
                        help="查询时的候选列表长度，越大越准越慢"
                    )

        submitted = st.form_submit_button("创建数据库并构建索引", type="primary")

        if submitted:
            # 保存当前输入
            st.session_state['form_name'] = name
            st.session_state['form_image_dir'] = image_dir
            st.session_state['form_num_workers'] = num_workers
            st.session_state['form_num_gpus'] = num_gpus

            if not name:
                st.session_state['create_result'] = ('error', "请输入数据库名称")
                st.rerun()
            elif not image_dir:
                st.session_state['create_result'] = ('error', "请输入图像目录路径")
                st.rerun()
            else:
                # 把表单参数组装成该库的配置，随库落盘为 config.yaml，
                # 索引构建时由 build_index 读取，因此这里填的值会真实生效。
                index_settings = {"type": index_type}
                if index_type in ("IVFFlat", "IVFPQ"):
                    index_settings["nlist"] = int(nlist)
                    index_settings["nprobe"] = int(nprobe)
                if index_type == "IVFPQ":
                    index_settings["m_pq"] = int(m_pq)
                    index_settings["nbits"] = int(nbits)
                if index_type == "HNSW":
                    index_settings["hnsw_m"] = int(hnsw_m)
                    index_settings["ef_construction"] = int(ef_construction)
                    index_settings["ef_search"] = int(ef_search)

                config = {
                    "text": {
                        "ocr": {
                            "engine": "transformers",
                            "languages": ocr_languages or ["ch", "en"],
                            "confidence_threshold": float(ocr_confidence),
                        },
                        "encoding": {
                            "chinese_model": chinese_model,
                            "english_model": english_model,
                            "embedding_dim": int(embedding_dim),
                            "max_length": int(max_length),
                        },
                    },
                    "image": {
                        "components": {
                            "perceptual_hash": {
                                "enabled": bool(enable_phash),
                                "algorithm": phash_algorithm,
                                "hash_size": int(hash_size),
                            },
                            "deep_features": {
                                "enabled": bool(enable_deep_features),
                                "model": cnn_model,
                                "output_dim": int(cnn_output_dim),
                            },
                        },
                        "batch_size": int(batch_size),
                    },
                    "index": index_settings,
                }

                try:
                    # 创建数据库
                    db_manager.create_database(
                        name,
                        Path(image_dir),
                        config_yaml=yaml.safe_dump(
                            config, allow_unicode=True, sort_keys=False
                        ),
                    )

                    # 任务 8.7：自动入队索引构建（带参数）
                    try:
                        from qsearch.webui.task_manager import TaskManager
                        task_manager = TaskManager(db_manager.databases_root)

                        # 使用配置的参数入队
                        task_id = task_manager.enqueue_index_build(
                            database_name=name,
                            num_workers=num_workers if num_gpus == 0 else None,
                            num_gpus=num_gpus,
                            batch_size=int(batch_size),
                            task_name=f"建立索引：{name}"
                        )

                        # 任务 8.8：创建成功后清空表单
                        st.session_state['form_name'] = ""
                        st.session_state['form_image_dir'] = ""
                        st.session_state['form_num_workers'] = None
                        st.session_state['form_num_gpus'] = 0

                        st.session_state['create_result'] = (
                            'success',
                            f"数据库「{name}」创建成功（任务 {task_id[:8]}），使用 "
                            f"{'GPU' if num_gpus > 0 else 'CPU'} 模式构建索引"
                        )
                        st.rerun()

                    except Exception as e:
                        # 任务 8.10：入队失败时数据集仍保留
                        st.session_state['create_result'] = (
                            'index_failed',
                            f"数据库「{name}」创建成功，但索引构建入队失败：{e}"
                        )
                        st.rerun()

                except DatabaseManagementError as e:
                    # 任务 8.8：创建失败时保留输入
                    st.session_state['create_result'] = ('error', f"创建失败：{e}")
                    st.rerun()



def build_index_dialog(db_manager: DatabaseManager, database_name: str):
    """建索引确认对话框。

    Args:
        db_manager: DatabaseManager 实例
        database_name: 数据库名
    """
    @st.dialog("建立索引")
    def show_dialog():
        st.write(f"为数据库「{database_name}」建立索引？")
        st.info("索引构建将在后台执行，可在「任务监控」页面查看进度。")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("确认", type="primary", width="stretch"):
                try:
                    from qsearch.webui.task_manager import TaskManager
                    task_manager = TaskManager(db_manager.databases_root)

                    task_id = task_manager.enqueue_index_build(
                        database_name=database_name,
                        task_name=f"建立索引：{database_name}"
                    )

                    st.session_state['build_result'] = ('ok', (database_name, task_id, 1))
                    st.session_state.pop('build_confirm', None)
                    st.rerun()

                except Exception as e:
                    st.session_state['build_result'] = ('error', str(e))
                    st.session_state.pop('build_confirm', None)
                    st.rerun()

        with col2:
            if st.button("取消", width="stretch"):
                st.session_state.pop('build_confirm', None)
                st.rerun()

    show_dialog()


if __name__ == "__main__":
    # 测试页面
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

    st.set_page_config(page_title="数据库管理", layout="wide")
    render_database_management_page(Path("./databases"))
