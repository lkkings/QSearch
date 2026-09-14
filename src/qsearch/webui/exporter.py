"""Data export module for QSearch WebUI.

Exports annotation data in multiple formats: JSONL, CSV, Excel.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from qsearch.webui.db_manager import get_database_manager

logger = logging.getLogger(__name__)


class Exporter:
    """Handles data export in multiple formats."""

    def __init__(self, database_path: Path):
        """Initialize exporter.

        Args:
            database_path: Path to database directory
        """
        self.database_path = Path(database_path)
        self.annotations_db = self.database_path / "annotations" / "annotations.db"
        self.db_manager = get_database_manager(self.annotations_db)

    def export_jsonl(
        self,
        output_path: Path,
        scope: str = "all",
        date_range: Optional[tuple] = None,
        progress_callback: Optional[callable] = None,
    ) -> int:
        """Export data to JSONL format (one query per line with nested results).

        Args:
            output_path: Output file path
            scope: Export scope ('all', 'labeled', 'completed')
            date_range: Optional (start_date, end_date) tuple
            progress_callback: Optional callback(current, total)

        Returns:
            Number of queries exported
        """
        queries = self._get_queries_for_export(scope, date_range)
        total = len(queries)

        with open(output_path, 'w', encoding='utf-8') as f:
            for idx, query in enumerate(queries):
                # Get candidates for this query
                candidates = self._get_candidates_for_query(query["query_id"])

                # Build nested structure
                record = {
                    "query_id": query["query_id"],
                    "query_image_path": query["query_image_path"],
                    "database_name": query["database_name"],
                    "top_n": query["top_n"],
                    "status": query["status"],
                    "created_at": query["created_at"],
                    "processing_time_ms": query["processing_time_ms"],
                    "candidates": [
                        {
                            "rank": c["rank"],
                            "image_path": c["candidate_image_path"],
                            "match_type": c["match_type"],
                            "confidence_level": c["confidence_level"],
                            "overall_score": c["overall_score"],
                            "text_score": c["text_score"],
                            "visual_score": c["visual_score"],
                            "hash_distance": c["hash_distance"],
                            "label": c["label"],
                            "notes": c["notes"],
                            "labeled_at": c["labeled_at"],
                        }
                        for c in candidates
                    ],
                }

                # Write as single line
                f.write(json.dumps(record, ensure_ascii=False) + '\n')

                if progress_callback and (idx + 1) % 10 == 0:
                    progress_callback(idx + 1, total)

        logger.info(f"Exported {total} queries to JSONL: {output_path}")
        return total

    def export_csv(
        self,
        output_path: Path,
        scope: str = "all",
        date_range: Optional[tuple] = None,
        progress_callback: Optional[callable] = None,
    ) -> int:
        """Export data to CSV format (flattened, one candidate per row).

        Args:
            output_path: Output file path
            scope: Export scope ('all', 'labeled', 'completed')
            date_range: Optional (start_date, end_date) tuple
            progress_callback: Optional callback(current, total)

        Returns:
            Number of rows exported
        """
        queries = self._get_queries_for_export(scope, date_range)
        rows = []

        for idx, query in enumerate(queries):
            candidates = self._get_candidates_for_query(query["query_id"])

            for candidate in candidates:
                rows.append({
                    "query_id": query["query_id"],
                    "query_image_path": query["query_image_path"],
                    "database_name": query["database_name"],
                    "query_created_at": query["created_at"],
                    "query_status": query["status"],
                    "candidate_rank": candidate["rank"],
                    "candidate_image_path": candidate["candidate_image_path"],
                    "match_type": candidate["match_type"],
                    "confidence_level": candidate["confidence_level"],
                    "overall_score": candidate["overall_score"],
                    "text_score": candidate["text_score"],
                    "visual_score": candidate["visual_score"],
                    "hash_distance": candidate["hash_distance"],
                    "label": candidate["label"],
                    "notes": candidate["notes"],
                    "labeled_at": candidate["labeled_at"],
                })

            if progress_callback and (idx + 1) % 10 == 0:
                progress_callback(idx + 1, len(queries))

        # Write to CSV with UTF-8 BOM for Excel compatibility
        df = pd.DataFrame(rows)
        df.to_csv(output_path, index=False, encoding='utf-8-sig')

        logger.info(f"Exported {len(rows)} rows to CSV: {output_path}")
        return len(rows)

    def export_excel(
        self,
        output_path: Path,
        scope: str = "all",
        date_range: Optional[tuple] = None,
        progress_callback: Optional[callable] = None,
    ) -> Dict[str, int]:
        """Export data to Excel format (multi-sheet: Queries, Candidates, Statistics).

        Args:
            output_path: Output file path
            scope: Export scope ('all', 'labeled', 'completed')
            date_range: Optional (start_date, end_date) tuple
            progress_callback: Optional callback(current, total)

        Returns:
            Dictionary with sheet names and row counts
        """
        queries = self._get_queries_for_export(scope, date_range)

        # Prepare queries sheet
        queries_data = []
        candidates_data = []

        for idx, query in enumerate(queries):
            queries_data.append({
                "Query ID": query["query_id"],
                "Query Image": query["query_image_path"],
                "Database": query["database_name"],
                "Top N": query["top_n"],
                "Status": query["status"],
                "Created At": query["created_at"],
                "Processing Time (ms)": query["processing_time_ms"],
            })

            # Get candidates
            candidates = self._get_candidates_for_query(query["query_id"])
            for candidate in candidates:
                candidates_data.append({
                    "Query ID": query["query_id"],
                    "Rank": candidate["rank"],
                    "Candidate Image": candidate["candidate_image_path"],
                    "Match Type": candidate["match_type"],
                    "Confidence": candidate["confidence_level"],
                    "Overall Score": candidate["overall_score"],
                    "Text Score": candidate["text_score"],
                    "Visual Score": candidate["visual_score"],
                    "Hash Distance": candidate["hash_distance"],
                    "Label": candidate["label"],
                    "Notes": candidate["notes"],
                    "Labeled At": candidate["labeled_at"],
                })

            if progress_callback and (idx + 1) % 10 == 0:
                progress_callback(idx + 1, len(queries))

        # Get statistics
        stats = self._get_statistics()

        stats_data = [
            {"Metric": "Total Queries", "Value": stats["total_queries"]},
            {"Metric": "Completed Queries", "Value": stats["completed_queries"]},
            {"Metric": "Unlabeled Queries", "Value": stats["unlabeled_queries"]},
            {"Metric": "Total Candidates", "Value": stats["total_candidates"]},
            {"Metric": "Labeled Candidates", "Value": stats["labeled_candidates"]},
            {"Metric": "Hit Candidates", "Value": stats["hit_candidates"]},
            {"Metric": "Miss Candidates", "Value": stats["miss_candidates"]},
            {"Metric": "Hit Rate", "Value": f"{stats['hit_rate']:.2%}"},
        ]

        # Add metadata
        metadata_data = [
            {"Field": "Export Date", "Value": datetime.utcnow().isoformat() + "Z"},
            {"Field": "Database", "Value": self.database_path.name},
            {"Field": "Export Scope", "Value": scope},
            {"Field": "Total Queries Exported", "Value": len(queries)},
            {"Field": "Total Candidates Exported", "Value": len(candidates_data)},
        ]

        # Create Excel file with formatting
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # Write sheets
            df_queries = pd.DataFrame(queries_data)
            df_candidates = pd.DataFrame(candidates_data)
            df_stats = pd.DataFrame(stats_data)
            df_metadata = pd.DataFrame(metadata_data)

            df_queries.to_excel(writer, sheet_name='Queries', index=False)
            df_candidates.to_excel(writer, sheet_name='Candidates', index=False)
            df_stats.to_excel(writer, sheet_name='Statistics', index=False)
            df_metadata.to_excel(writer, sheet_name='Metadata', index=False)

            # Auto-width columns
            for sheet_name in writer.sheets:
                worksheet = writer.sheets[sheet_name]
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width

                # Freeze header row
                worksheet.freeze_panes = 'A2'

        result = {
            "Queries": len(queries_data),
            "Candidates": len(candidates_data),
            "Statistics": len(stats_data),
            "Metadata": len(metadata_data),
        }

        logger.info(f"Exported to Excel: {output_path}")
        return result

    def _get_queries_for_export(
        self,
        scope: str,
        date_range: Optional[tuple] = None,
    ) -> List[Dict]:
        """Get queries based on export scope and date range.

        Args:
            scope: Export scope ('all', 'labeled', 'completed')
            date_range: Optional (start_date, end_date) tuple

        Returns:
            List of query dictionaries
        """
        conditions = []
        params = []

        # Scope filter
        if scope == "labeled":
            conditions.append("status IN ('partial', 'completed')")
        elif scope == "completed":
            conditions.append("status = 'completed'")
        # 'all' means no filter

        # Date range filter
        if date_range:
            start_date, end_date = date_range
            conditions.append("created_at BETWEEN ? AND ?")
            params.extend([start_date, end_date])

        # Build query
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        query_sql = f"SELECT * FROM queries WHERE {where_clause} ORDER BY created_at"

        rows = self.db_manager.execute_query(query_sql, tuple(params) if params else None)
        return [dict(row) for row in rows]

    def _get_candidates_for_query(self, query_id: str) -> List[Dict]:
        """Get all candidates for a query.

        Args:
            query_id: Query ID

        Returns:
            List of candidate dictionaries
        """
        query_sql = """
            SELECT * FROM candidates
            WHERE query_id = ?
            ORDER BY match_type, rank
        """

        rows = self.db_manager.execute_query(query_sql, (query_id,))
        return [dict(row) for row in rows]

    def _get_statistics(self) -> Dict:
        """Get current statistics from database.

        Returns:
            Statistics dictionary
        """
        stats_sql = "SELECT * FROM stats_summary"
        result = self.db_manager.execute_query(stats_sql, fetch_one=True)

        if result:
            return {
                "total_queries": result["total_queries"] or 0,
                "completed_queries": result["completed_queries"] or 0,
                "unlabeled_queries": result["unlabeled_queries"] or 0,
                "total_candidates": result["total_candidates"] or 0,
                "labeled_candidates": result["labeled_candidates"] or 0,
                "hit_candidates": result["hit_candidates"] or 0,
                "miss_candidates": result["miss_candidates"] or 0,
                "hit_rate": float(result["hit_rate"] or 0.0),
            }

        return {
            "total_queries": 0,
            "completed_queries": 0,
            "unlabeled_queries": 0,
            "total_candidates": 0,
            "labeled_candidates": 0,
            "hit_candidates": 0,
            "miss_candidates": 0,
            "hit_rate": 0.0,
        }

    @staticmethod
    def generate_filename(
        database_name: str,
        format: str,
        scope: str = "all",
    ) -> str:
        """Generate export filename with timestamp.

        Args:
            database_name: Database name
            format: Export format ('jsonl', 'csv', 'xlsx')
            scope: Export scope

        Returns:
            Sanitized filename with timestamp
        """
        # Sanitize database name
        safe_name = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in database_name)

        # Generate timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        # Build filename
        filename = f"{safe_name}_{scope}_{timestamp}.{format}"

        return filename
