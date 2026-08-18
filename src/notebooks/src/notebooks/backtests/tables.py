"""Reusable HTML table displays for notebook result DataFrames."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html import escape

import pandas as pd
from IPython.display import HTML
from IPython.display import display as ipython_display

from notebooks.backtests.results import TaskResultFrames


@dataclass(frozen=True, slots=True)
class DataFrameTableSpec:
    """Presentation settings for one notebook DataFrame table."""

    frame: pd.DataFrame
    title: str
    table_id: str
    page_size: int = 100

    @property
    def safe_table_id(self) -> str:
        """Return a CSS and DOM-safe table id."""
        normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", self.table_id.strip()).strip("-")
        return normalized or "notebook-table"


@dataclass(frozen=True, slots=True)
class SortablePaginatedDataFrameDisplay:
    """Render a DataFrame as a sortable, paginated notebook HTML table."""

    page_size: int = 100

    def display(self, frame: pd.DataFrame, *, title: str, table_id: str) -> None:
        """Display one DataFrame in the current IPython output area."""
        ipython_display(HTML(self.html(frame, title=title, table_id=table_id)))

    def html(self, frame: pd.DataFrame, *, title: str, table_id: str) -> str:
        """Return the HTML for one sortable, paginated DataFrame."""
        spec = DataFrameTableSpec(
            frame=frame,
            title=title,
            table_id=table_id,
            page_size=self.page_size,
        )
        if spec.frame.empty:
            return self._empty_html(spec)
        return self._table_html(spec)

    def _empty_html(self, spec: DataFrameTableSpec) -> str:
        table_id = escape(spec.safe_table_id)
        return f"""
        <section class="paged-frame" id="{table_id}">
            <h3>{escape(spec.title)}</h3>
            <p>0 rows</p>
        </section>
        """

    def _table_html(self, spec: DataFrameTableSpec) -> str:
        table_id = spec.safe_table_id
        table_html = spec.frame.to_html(
            index=False,
            escape=True,
            max_rows=None,
            max_cols=None,
            border=0,
            classes="paged-table",
        )
        return f"""
        <section class="paged-frame" id="{escape(table_id)}">
            {self._style(table_id)}
            <h3>{escape(spec.title)}</h3>
            <div class="paged-toolbar">
                <button type="button" data-prev>Prev</button>
                <span data-page-label></span>
                <button type="button" data-next>Next</button>
            </div>
            <div class="paged-scroll">{table_html}</div>
            {self._script(table_id=table_id, page_size=spec.page_size)}
        </section>
        """

    @staticmethod
    def _style(table_id: str) -> str:
        css_id = f"#{table_id}"
        return f"""
        <style>
            {css_id} {{ margin: 16px 0 28px; }}
            {css_id} h3 {{ margin: 0 0 8px; font-size: 16px; }}
            {css_id} .paged-toolbar {{
                align-items: center;
                display: flex;
                gap: 8px;
                margin-bottom: 8px;
            }}
            {css_id} .paged-toolbar button {{
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                background: #f8fafc;
                cursor: pointer;
                padding: 4px 10px;
            }}
            {css_id} .paged-toolbar button:disabled {{
                color: #94a3b8;
                cursor: default;
            }}
            {css_id} .paged-scroll {{ overflow-x: auto; }}
            {css_id} table.paged-table {{
                border-collapse: collapse;
                font-size: 12px;
                white-space: nowrap;
                width: max-content;
            }}
            {css_id} table.paged-table th,
            {css_id} table.paged-table td {{
                border: 1px solid #e2e8f0;
                padding: 4px 8px;
                text-align: left;
                vertical-align: top;
            }}
            {css_id} table.paged-table th {{
                background: #f8fafc;
                cursor: pointer;
                user-select: none;
            }}
            {css_id} table.paged-table th.sorted-asc::after {{ content: " asc"; }}
            {css_id} table.paged-table th.sorted-desc::after {{ content: " desc"; }}
        </style>
        """

    @staticmethod
    def _script(*, table_id: str, page_size: int) -> str:
        table_id_json = json.dumps(table_id)
        return f"""
        <script>
        (() => {{
            const root = document.getElementById({table_id_json});
            if (!root) return;
            const tbody = root.querySelector("tbody");
            const headers = Array.from(root.querySelectorAll("thead th"));
            const pageSize = {page_size};
            let rows = Array.from(root.querySelectorAll("tbody tr"));
            let currentPage = 0;
            let sortColumn = null;
            let sortDirection = "asc";
            const label = root.querySelector("[data-page-label]");
            const prev = root.querySelector("[data-prev]");
            const next = root.querySelector("[data-next]");
            const pageCount = () => Math.max(1, Math.ceil(rows.length / pageSize));
            const render = () => {{
                const start = currentPage * pageSize;
                const end = start + pageSize;
                rows.forEach((row, index) => {{
                    row.style.display = index >= start && index < end ? "" : "none";
                }});
                label.textContent =
                    `Page ${{currentPage + 1}} / ${{pageCount()}} (${{rows.length}} rows)`;
                prev.disabled = currentPage === 0;
                next.disabled = currentPage >= pageCount() - 1;
            }};
            const numericValue = (text) => {{
                const normalized = text.replace(/,/g, "").replace(/\\s+[A-Z]{{3}}$/, "");
                if (normalized.trim() === "") return null;
                const value = Number(normalized);
                return Number.isNaN(value) ? null : value;
            }};
            const cellValue = (row, columnIndex) => {{
                const text = (row.children[columnIndex]?.textContent || "").trim();
                const number = numericValue(text);
                if (number !== null) return {{ type: "number", value: number }};
                const dateValue = Date.parse(text);
                if (!Number.isNaN(dateValue) && /[-:]/.test(text)) {{
                    return {{ type: "date", value: dateValue }};
                }}
                return {{ type: "text", value: text.toLocaleLowerCase() }};
            }};
            const compareRows = (left, right, columnIndex) => {{
                const leftValue = cellValue(left, columnIndex);
                const rightValue = cellValue(right, columnIndex);
                if (
                    leftValue.type === rightValue.type &&
                    leftValue.value < rightValue.value
                ) return -1;
                if (
                    leftValue.type === rightValue.type &&
                    leftValue.value > rightValue.value
                ) return 1;
                return leftValue.value.toString().localeCompare(rightValue.value.toString());
            }};
            const sortRows = (columnIndex) => {{
                sortDirection =
                    sortColumn === columnIndex && sortDirection === "asc" ? "desc" : "asc";
                sortColumn = columnIndex;
                rows = rows.slice().sort((left, right) => compareRows(left, right, columnIndex));
                if (sortDirection === "desc") rows.reverse();
                rows.forEach((row) => tbody.appendChild(row));
                headers.forEach((header, index) => {{
                    header.classList.toggle(
                        "sorted-asc",
                        index === sortColumn && sortDirection === "asc",
                    );
                    header.classList.toggle(
                        "sorted-desc",
                        index === sortColumn && sortDirection === "desc",
                    );
                }});
                currentPage = 0;
                render();
            }};
            headers.forEach((header, index) => {{
                header.addEventListener("click", () => sortRows(index));
            }});
            prev.addEventListener("click", () => {{
                if (currentPage > 0) {{
                    currentPage -= 1;
                    render();
                }}
            }});
            next.addEventListener("click", () => {{
                if (currentPage < pageCount() - 1) {{
                    currentPage += 1;
                    render();
                }}
            }});
            render();
        }})();
        </script>
        """


@dataclass(frozen=True, slots=True)
class TaskResultFrameDisplay:
    """Display the standard result frames for a backtest task."""

    table_display: SortablePaginatedDataFrameDisplay = field(
        default_factory=SortablePaginatedDataFrameDisplay
    )

    def display(self, frames: TaskResultFrames) -> None:
        """Display task, cycle, trade, and event tables."""
        self.table_display.display(frames.task, title="Task Summary", table_id="task-summary")
        self.table_display.display(frames.cycles, title="Cycle Summary", table_id="cycle-summary")
        self.table_display.display(frames.trades, title="Trade Summary", table_id="trade-summary")
        self.table_display.display(
            frames.events,
            title="Strategy Events",
            table_id="strategy-events",
        )
