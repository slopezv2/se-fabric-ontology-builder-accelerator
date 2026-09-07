"""Generate a traceable OWL ontology from Fabric table metadata."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from owlready2 import AnnotationProperty, DataProperty, ObjectProperty, Thing, get_ontology, types
from rdflib import Graph


BASE_IRI = "https://example.com/fabric-ontology/"
TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+((?:`[^`]+`\.){2}`[^`]+`)\s*\((.*?)\)\s*USING",
    re.IGNORECASE | re.DOTALL,
)
PK_RE = re.compile(
    r"ALTER\s+TABLE\s+((?:`[^`]+`\.){2}`[^`]+`)\s+ADD\s+CONSTRAINT\s+`?[^`\s]+`?\s+PRIMARY\s+KEY\s*\(([^)]+)\)",
    re.IGNORECASE,
)
FK_RE = re.compile(
    r"ALTER\s+TABLE\s+((?:`[^`]+`\.){2}`[^`]+`)\s+ADD\s+CONSTRAINT\s+`?([^`\s]+)`?\s+FOREIGN\s+KEY\s*\(([^)]+)\)\s+REFERENCES\s+((?:`[^`]+`\.){2}`[^`]+`)\s*\(([^)]+)\)",
    re.IGNORECASE,
)
COLUMN_RE = re.compile(
    r"^\s*`([^`]+)`\s+(.+?)(?:\s+COMMENT\s+'((?:''|[^'])*)')?,?\s*$",
    re.IGNORECASE,
)


@dataclass
class Column:
    name: str
    data_type: str
    comment: str | None
    nullable: bool


@dataclass
class Table:
    qualified_name: str
    catalog: str
    schema: str
    name: str
    comment: str | None
    columns: list[Column] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)


@dataclass
class ForeignKey:
    source_table: str
    constraint: str
    source_columns: list[str]
    target_table: str
    target_columns: list[str]


def unquote_identifier(value: str) -> str:
    return value.strip().strip("`").strip()


def qualified_parts(value: str) -> tuple[str, str, str]:
    parts = [unquote_identifier(part) for part in value.split(".")]
    if len(parts) != 3:
        raise ValueError(f"Expected catalog.schema.table identifier: {value}")
    return parts[0], parts[1], parts[2]


def qualified_name(value: str) -> str:
    return ".".join(qualified_parts(value))


def column_names(value: str) -> list[str]:
    return [unquote_identifier(item) for item in value.split(",")]


def local_name(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not result or result[0].isdigit():
        result = f"n_{result}"
    return result


def business_name(identifier: str, comment: str | None = None) -> str:
    """Create a readable label while retaining the exact source identifier."""
    if comment:
        description = re.split(r"[.!?]\s+", comment.strip(), maxsplit=1)[0]
        if description:
            return description[:120]
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", identifier)
    words = re.sub(r"[_-]+", " ", words)
    return " ".join(words.split()).title()


def markdown_section(text: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\s*$\n(.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1) if match else ""


def markdown_rows(section: str, columns: int) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != columns or all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows[1:] if rows else []


def evidence_from(text: str) -> str:
    for evidence in ("Verified", "Derived", "Proposed"):
        if evidence.lower() in text.lower():
            return evidence
    return "Proposed"


def business_rule_data(rules_text: str) -> tuple[dict[str, str], list[list[str]], list[list[str]]]:
    inventory_rows = markdown_rows(markdown_section(rules_text, "Table Inventory"), 7)
    table_labels = {
        row[0].strip("`"): row[1]
        for row in inventory_rows
        if row[0].startswith("`") and row[1]
    }
    metric_rows = markdown_rows(markdown_section(rules_text, "Business Metrics for Testing"), 5)
    rule_rows = markdown_rows(markdown_section(rules_text, "Business Restrictions and Data-Quality Rules"), 5)
    return table_labels, metric_rows, rule_rows


def iri_path(*parts: str) -> str:
    return BASE_IRI + "/".join(quote(part, safe="") for part in parts)


def xsd_type(data_type: str):  # noqa: ANN202
    normalized = data_type.lower()
    if any(token in normalized for token in ("string", "varchar", "char")):
        return str
    if "boolean" in normalized:
        return bool
    if normalized.startswith("date") and "timestamp" not in normalized:
        return dt.date
    if "timestamp" in normalized:
        return dt.datetime
    if any(token in normalized for token in ("decimal", "numeric", "double", "float")):
        return float
    if any(token in normalized for token in ("int", "bigint", "smallint", "tinyint")):
        return int
    return str


def canonicalize_rdfxml(path: Path) -> None:
    namespaces = {
        "": BASE_IRI + "ontology#",
        "owl": "http://www.w3.org/2002/07/owl#",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "xsd": "http://www.w3.org/2001/XMLSchema#",
    }
    for prefix, namespace in namespaces.items():
        ET.register_namespace(prefix, namespace)

    tree = ET.parse(path)

    def sort_element(element: ET.Element) -> None:
        for child in element:
            sort_element(child)
        attributes = sorted(element.attrib.items())
        element.attrib.clear()
        element.attrib.update(attributes)
        element[:] = sorted(
            element,
            key=lambda child: (
                child.tag,
                tuple(child.attrib.items()),
                child.text or "",
                ET.tostring(child, encoding="unicode"),
            ),
        )
        if element.text is not None and not element.text.strip():
            element.text = None
        for child in element:
            if child.tail is not None and not child.tail.strip():
                child.tail = None

    sort_element(tree.getroot())
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def parse_metadata(path: Path) -> tuple[list[Table], list[ForeignKey]]:
    text = path.read_text(encoding="utf-8")
    if text.lstrip().startswith(("{", "[")):
        return parse_json_metadata(json.loads(text))

    tables: list[Table] = []
    for match in TABLE_RE.finditer(text):
        catalog, schema, name = qualified_parts(match.group(1))
        body = match.group(2)
        comment_match = re.search(r"COMMENT\s+'((?:''|[^'])*)'", text[match.end() : match.end() + 500], re.I)
        columns: list[Column] = []
        for line in body.splitlines():
            column_match = COLUMN_RE.match(line)
            if not column_match:
                continue
            column_name, column_type, comment = column_match.groups()
            nullable = "NOT NULL" not in column_type.upper()
            source_type = re.sub(r"\s+NOT\s+NULL\b", "", column_type, flags=re.IGNORECASE).strip()
            columns.append(
                Column(
                    column_name,
                    source_type,
                    comment.replace("''", "'") if comment else None,
                    nullable,
                )
            )
        tables.append(Table(".".join((catalog, schema, name)), catalog, schema, name, comment_match.group(1) if comment_match else None, columns))

    table_by_name = {table.qualified_name: table for table in tables}
    for match in PK_RE.finditer(text):
        table = table_by_name.get(qualified_name(match.group(1)))
        if table:
            table.primary_key = column_names(match.group(2))

    foreign_keys = [
        ForeignKey(qualified_name(match.group(1)), match.group(2), column_names(match.group(3)), qualified_name(match.group(4)), column_names(match.group(5)))
        for match in FK_RE.finditer(text)
    ]
    return tables, foreign_keys


def parse_json_metadata(document: object) -> tuple[list[Table], list[ForeignKey]]:
    raw_tables = document.get("tables", document) if isinstance(document, dict) else document
    tables: list[Table] = []
    for item in raw_tables:
        catalog = item.get("catalog", "")
        schema = item.get("schema", "")
        name = item.get("table") or item.get("name")
        columns = [Column(column.get("name") or column.get("column_name"), column.get("data_type", "string"), column.get("comment"), column.get("nullable", True)) for column in item.get("columns", [])]
        tables.append(Table(".".join(filter(None, (catalog, schema, name))), catalog, schema, name, item.get("comment") or item.get("table_comment"), columns, item.get("primary_key", item.get("primary_keys", []))))
    foreign_keys: list[ForeignKey] = []
    for item in (document.get("foreign_keys", []) if isinstance(document, dict) else []):
        foreign_keys.append(ForeignKey(item["source_table"], item.get("constraint", "foreignKey"), item["source_columns"], item["target_table"], item["target_columns"]))
    return tables, foreign_keys


def generate(
    metadata_path: Path,
    rules_path: Path,
    output_path: Path,
    mapping_path: Path | None = None,
) -> tuple[int, int, int]:
    tables, foreign_keys = parse_metadata(metadata_path)
    rules_text = rules_path.read_text(encoding="utf-8")
    table_labels, metric_rows, rule_rows = business_rule_data(rules_text)
    ontology = get_ontology(BASE_IRI + "ontology")

    with ontology:
        class TableEntity(Thing):  # noqa: F405
            pass

        class BusinessRule(Thing):  # noqa: F405
            pass

        class Metric(Thing):  # noqa: F405
            pass

        class sourceTableName(AnnotationProperty):  # noqa: N801,F405
            pass

        class sourceCatalogName(AnnotationProperty):  # noqa: N801,F405
            pass

        class sourceSchemaName(AnnotationProperty):  # noqa: N801,F405
            pass

        class sourceColumnName(AnnotationProperty):  # noqa: N801,F405
            pass

        class sourceDataType(AnnotationProperty):  # noqa: N801,F405
            pass

        class sourceNullable(AnnotationProperty):  # noqa: N801,F405
            pass

        class sourceComment(AnnotationProperty):  # noqa: N801,F405
            pass

        class evidenceLevel(AnnotationProperty):  # noqa: N801,F405
            pass

        class primaryKeyColumn(AnnotationProperty):  # noqa: N801,F405
            pass

        class primaryKeyDefinition(AnnotationProperty):  # noqa: N801,F405
            pass

        class sourceConstraint(AnnotationProperty):  # noqa: N801,F405
            pass

        class targetTableName(AnnotationProperty):  # noqa: N801,F405
            pass

        class targetColumnName(AnnotationProperty):  # noqa: N801,F405
            pass

        class constraintEnforcement(AnnotationProperty):  # noqa: N801,F405
            pass

        class sourceFile(AnnotationProperty):  # noqa: N801,F405
            pass

        class provenanceText(AnnotationProperty):  # noqa: N801,F405
            pass

        class ruleText(AnnotationProperty):  # noqa: N801,F405
            pass

        class metricText(AnnotationProperty):  # noqa: N801,F405
            pass

        class ruleTitle(AnnotationProperty):  # noqa: N801,F405
            pass

        class ruleScopeTypeSeverity(AnnotationProperty):  # noqa: N801,F405
            pass

        class metricQuestionAndFormula(AnnotationProperty):  # noqa: N801,F405
            pass

        class metricGrainAndDimensions(AnnotationProperty):  # noqa: N801,F405
            pass

        class metricNullHandlingAndUnit(AnnotationProperty):  # noqa: N801,F405
            pass

        class generatedAtTime(AnnotationProperty):  # noqa: N801,F405
            pass

        class generatedFrom(AnnotationProperty):  # noqa: N801,F405
            pass

        class sourceReference(AnnotationProperty):  # noqa: N801,F405
            pass

        table_classes: dict[str, object] = {}
        data_properties: dict[tuple[str, str], object] = {}
        mapping = {
            "ontology_iri": BASE_IRI + "ontology",
            "metadata_file": str(metadata_path),
            "business_rules_file": str(rules_path),
            "tables": [],
            "fields": [],
            "relationships": [],
        }
        for table in tables:
            class_name = f"Table_{local_name(table.catalog)}_{local_name(table.schema)}_{local_name(table.name)}"
            table_class = types.new_class(class_name, (TableEntity,))
            table_class.iri = iri_path("table", table.catalog, table.schema, table.name)
            table_label = table_labels.get(table.qualified_name, business_name(table.name))
            table_class.label = [table_label]
            table_class.sourceTableName = [table.qualified_name]
            table_class.sourceCatalogName = [table.catalog]
            table_class.sourceSchemaName = [table.schema]
            table_class.sourceFile = [str(metadata_path)]
            table_class.evidenceLevel = ["Verified"]
            if table.comment:
                table_class.comment = [table.comment]
                table_class.sourceComment = [table.comment]
            for key in table.primary_key:
                table_class.primaryKeyColumn.append(key)
            table_class.primaryKeyDefinition = [json.dumps(table.primary_key, ensure_ascii=False)]
            table_classes[table.qualified_name] = table_class
            mapping["tables"].append(
                {
                    "source_name": table.qualified_name,
                    "business_name": table_label,
                    "class_iri": table_class.iri,
                    "primary_key": table.primary_key,
                }
            )
            for column in table.columns:
                property_name = f"Property_{local_name(table.catalog)}_{local_name(table.schema)}_{local_name(table.name)}_{local_name(column.name)}"
                prop = types.new_class(property_name, (DataProperty,))  # noqa: F405
                prop.iri = iri_path("property", table.catalog, table.schema, table.name, column.name)
                prop.domain = [table_class]
                prop.range = [xsd_type(column.data_type)]
                field_label = business_name(column.name, column.comment)
                prop.label = [field_label]
                prop.sourceTableName = [table.qualified_name]
                prop.sourceColumnName = [column.name]
                prop.sourceDataType = [column.data_type]
                prop.sourceNullable = [str(column.nullable).lower()]
                prop.sourceFile = [str(metadata_path)]
                prop.evidenceLevel = ["Verified"]
                if column.comment:
                    prop.comment = [column.comment]
                    prop.sourceComment = [column.comment]
                data_properties[(table.qualified_name, column.name)] = prop
                mapping["fields"].append(
                    {
                        "source_table": table.qualified_name,
                        "source_name": column.name,
                        "business_name": field_label,
                        "property_iri": prop.iri,
                        "data_type": column.data_type,
                    }
                )

        for foreign_key in foreign_keys:
            source = table_classes.get(foreign_key.source_table)
            target = table_classes.get(foreign_key.target_table)
            if source is None or target is None:
                continue
            for source_column, target_column in zip(foreign_key.source_columns, foreign_key.target_columns):
                name = f"Relationship_{local_name(foreign_key.source_table)}_{local_name(source_column)}_{local_name(foreign_key.target_table)}_{local_name(target_column)}"
                prop = types.new_class(name, (ObjectProperty,))  # noqa: F405
                prop.iri = iri_path("relationship", foreign_key.source_table, source_column, foreign_key.target_table, target_column)
                prop.domain = [source]
                prop.range = [target]
                relationship_label = (
                    f"{table_labels.get(foreign_key.source_table, business_name(foreign_key.source_table.rsplit('.', 1)[-1]))} "
                    f"to {table_labels.get(foreign_key.target_table, business_name(foreign_key.target_table.rsplit('.', 1)[-1]))}"
                )
                prop.label = [relationship_label]
                prop.sourceTableName = [foreign_key.source_table]
                prop.sourceColumnName = [source_column]
                prop.sourceConstraint = [foreign_key.constraint]
                prop.targetTableName = [foreign_key.target_table]
                prop.targetColumnName = [target_column]
                prop.constraintEnforcement = ["Unspecified in source metadata"]
                prop.provenanceText = [f"{foreign_key.source_table}.{source_column} -> {foreign_key.target_table}.{target_column}"]
                prop.evidenceLevel = ["Verified"]
                mapping["relationships"].append(
                    {
                        "constraint": foreign_key.constraint,
                        "business_name": relationship_label,
                        "source_table": foreign_key.source_table,
                        "source_column": source_column,
                        "target_table": foreign_key.target_table,
                        "target_column": target_column,
                        "property_iri": prop.iri,
                    }
                )

        for row in rule_rows:
            rule_id, title, scope_type_severity, test_logic, evidence_text = row
            rule = BusinessRule(rule_id.replace("-", "_"))
            rule.iri = iri_path("rule", rule_id)
            rule.label = [f"{rule_id}: {title}"]
            rule.ruleTitle = [title]
            rule.ruleScopeTypeSeverity = [scope_type_severity]
            rule.ruleText = [test_logic]
            rule.evidenceLevel = [evidence_from(evidence_text)]
            rule.provenanceText = [evidence_text]
            rule.generatedFrom = [str(rules_path)]
            rule.sourceReference = sorted(set(re.findall(r"`([^`]+)`", " | ".join(row))))

        for index, row in enumerate(metric_rows, start=1):
            metric_id = f"MET-{index:03d}"
            name, question_and_formula, grain, null_handling, evidence_text = row
            metric = Metric(metric_id.replace("-", "_"))
            metric.iri = iri_path("metric", metric_id)
            metric.label = [name]
            metric.metricText = [" | ".join(row)]
            metric.metricQuestionAndFormula = [question_and_formula]
            metric.metricGrainAndDimensions = [grain]
            metric.metricNullHandlingAndUnit = [null_handling]
            metric.evidenceLevel = [evidence_from(evidence_text)]
            metric.provenanceText = [evidence_text]
            metric.generatedFrom = [str(rules_path)]
            metric.sourceReference = sorted(set(re.findall(r"`([^`]+)`", " | ".join(row))))

        ontology.label = ["example UDV Fabric Ontology"]
        ontology.comment = [f"Generated from {metadata_path} and {rules_path}"]
        ontology.sourceFile = [str(metadata_path), str(rules_path)]
        generated_at = dt.datetime.fromtimestamp(
            max(metadata_path.stat().st_mtime, rules_path.stat().st_mtime),
            tz=dt.UTC,
        ).isoformat()
        ontology.generatedAtTime = [generated_at]
        ontology.provenanceText = [
            f"namespace={BASE_IRI}; tables={len(tables)}; columns={sum(len(table.columns) for table in tables)}; "
            f"primary_keys={sum(bool(table.primary_key) for table in tables)}; foreign_keys={len(foreign_keys)}; "
            f"business_rules={len(rule_rows)}; metrics={len(metric_rows)}; parse_errors=0"
        ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ontology.save(file=str(output_path), format="rdfxml")
    canonicalize_rdfxml(output_path)
    turtle_path = output_path.with_suffix(".ttl")
    graph = Graph()
    graph.parse(output_path, format="xml")
    graph.serialize(destination=turtle_path, format="turtle")
    mapping_path = mapping_path or output_path.with_name(f"{output_path.stem}_mapping.json")
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(tables), sum(len(table.columns) for table in tables), len(foreign_keys)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=Path("inputs/lakehouse_tables/example_udv_tables.txt"))
    parser.add_argument("--rules", type=Path, default=Path("out/business_rules/business_rules.md"))
    parser.add_argument("--output", type=Path, default=Path("out/ontologies/example_udv_ontology.owl"))
    parser.add_argument("--mapping", type=Path)
    args = parser.parse_args()
    counts = generate(args.metadata, args.rules, args.output, args.mapping)
    mapping = args.mapping or args.output.with_name(f"{args.output.stem}_mapping.json")
    print(f"Generated {args.output} (tables={counts[0]}, columns={counts[1]}, foreign_keys={counts[2]})")
    print(f"Mapping written to {mapping}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())