import pandas as pd
import numpy as np
import re
from dataclasses import dataclass
from typing import List, Dict, Any

@dataclass
class EvidenceDocument:
    doc_id: str
    source_type: str
    fenced_text: str
    raw_text: str
    matched_terms: List[str]
    relevance_score: float

class UnstructuredCorroborator:
    """Stage 8: TF-IDF retrieval over unstructured logs and tickets with 
    untrusted prompt-injection fencing[cite: 3].
    """

    def __init__(self, evidence_csv_path: str):
        self.evidence_path = evidence_csv_path
        self.df = self.load_evidence()

    def load_evidence(self) -> pd.DataFrame:
        """Loads unstructured evidence CSV[cite: 1]."""
        try:
            df = pd.read_csv(self.evidence_path)
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
            return df
        except Exception as e:
            return pd.DataFrame(columns=['doc_id', 'date', 'source_type', 'text', 'region', 'category'])

    @staticmethod
    def fence_untrusted_text(doc_id: str, raw_text: str) -> str:
        """Strips injection delimiters and wraps text in protective boundary[cite: 3]."""
        sanitized = re.sub(r'<<<.*?>>>', '', str(raw_text))
        sanitized = sanitized.replace('```', '')
        return f"<<<DOC id='{doc_id}'>>>\n{sanitized}\n<<<END>>>"

    def retrieve_corroboration(
        self,
        keywords: List[str],
        target_date: str,
        region: str = None,
        category: str = None,
        top_k: int = 3
    ) -> List[EvidenceDocument]:
        """Retrieves and ranks relevant text evidence using TF-IDF term matching[cite: 3]."""
        if self.df.empty:
            return []

        filtered_df = self.df.copy()
        target_dt = pd.to_datetime(target_date)

        if 'date' in filtered_df.columns:
            start_dt = target_dt - pd.Timedelta(days=3)
            end_dt = target_dt + pd.Timedelta(days=3)
            filtered_df = filtered_df[(filtered_df['date'] >= start_dt) & (filtered_df['date'] <= end_dt)]

        if region and 'region' in filtered_df.columns:
            filtered_df = filtered_df[filtered_df['region'].isin([region, 'ALL'])]
        if category and 'category' in filtered_df.columns:
            filtered_df = filtered_df[filtered_df['category'].isin([category, 'ALL'])]

        if filtered_df.empty:
            return []

        docs_list = []
        num_docs = len(filtered_df)

        for _, row in filtered_df.iterrows():
            doc_text = str(row.get('text', '')).lower()
            matched_terms = []
            score = 0.0

            for kw in keywords:
                kw_lower = kw.lower()
                tf = doc_text.count(kw_lower)
                if tf > 0:
                    matched_terms.append(kw)
                    idf = np.log((num_docs + 1.0) / (1.0 + sum(1 for t in filtered_df['text'] if kw_lower in str(t).lower())))
                    score += tf * idf

            if score > 0:
                doc_id = str(row.get('doc_id', 'DOC_UNKNOWN'))
                raw_text_str = str(row.get('text', ''))
                fenced = self.fence_untrusted_text(doc_id, raw_text_str)

                docs_list.append(
                    EvidenceDocument(
                        doc_id=doc_id,
                        source_type=str(row.get('source_type', 'general')),
                        fenced_text=fenced,
                        raw_text=raw_text_str,
                        matched_terms=matched_terms,
                        relevance_score=round(float(score), 4)
                    )
                )

        docs_list.sort(key=lambda x: x.relevance_score, reverse=True)
        return docs_list[:top_k]
