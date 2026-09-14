"""SearchEngine 的匹配执行层。

封装 QuestionMatcher 并持有索引引用。
"""

import logging
from pathlib import Path
from typing import Dict, List

from qsearch.indexing.faiss_index import FaissIndexBuilder
from qsearch.indexing.hash_index import HashIndex
from qsearch.matching.matchers import ContentMatcher, ExactMatcher, QuestionMatcher

logger = logging.getLogger(__name__)


class MatcherWrapper:
    """封装 QuestionMatcher 的匹配执行层。

    持有索引引用，但不负责加载索引或提取特征。
    """

    def __init__(
        self,
        matcher: QuestionMatcher,
        faiss_index: FaissIndexBuilder,
        hash_index: HashIndex,
        features_db: Dict[str, Dict],
    ):
        """初始化 matcher。

        Args:
            matcher: 已构建的 QuestionMatcher 实例
            faiss_index: FAISS 索引
            hash_index: 哈希索引
            features_db: 特征数据库
        """
        self.matcher = matcher
        self.faiss_index = faiss_index
        self.hash_index = hash_index
        self.features_db = features_db

    def match(self, query_features: Dict, top_n: int = 10) -> Dict:
        """执行匹配。

        Args:
            query_features: 查询图像的特征字典
            top_n: 返回的最大结果数

        Returns:
            匹配结果字典
        """
        return self.matcher.match(query_features, top_n=top_n)

    def match_batch(
        self,
        query_features_list: List[Dict],
        top_n: int = 10,
        vector_batch_size: int = 1024,
    ) -> List[Dict]:
        """Execute vector retrieval for multiple queries in batches."""
        return self.matcher.match_batch(
            query_features_list,
            top_n=top_n,
            vector_batch_size=vector_batch_size,
        )
