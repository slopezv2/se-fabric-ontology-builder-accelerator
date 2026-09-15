"""Transform RDF/OWL and source mappings into Fabric Ontology definition parts."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rdflib import Graph, OWL, RDF, RDFS, URIRef


FABRIC_NAMESPACE = "usertypes"
FABRIC_NAMESPACE_TYPE = "Custom"
FABRIC_VISIBILITY = "Visible"
ID_MAX = (1 << 63) - 1
UUID_NAMESPACE = uuid.UUID("b58d8b8e-45e7-5d90-beca-948692bb32a0")
XSD_VALUE_TYPES = {
    "http://www.w3.org/2001/XMLSchema#boolean": "Boolean",
    "http://www.w3.org/2001/XMLSchema#date": "DateTime",
    "http://www.w3.org/2001/XMLSchema#dateTime": "DateTime",
    "http://www.w3.org/2001/XMLSchema#decimal": "Double",
    "http://www.w3.org/2001/XMLSchema#double": "Double",
    "http://www.w3.org/2001/XMLSchema#float": "Double",
    "http://www.w3.org/2001/XMLSchema#integer": "BigInt",
    "http://www.w3.org/2001/XMLSchema#int": "BigInt",
    "http://www.w3.org/2001/XMLSchema#long": "BigInt",
    "http://www.w3.org/2001/XMLSchema#string": "String",
}
FABRIC_KEY_VALUE_TYPES = {"BigInt", "String"}


@dataclass(frozen=True)
class TransformConfig:
    ontology_path: Path
    mapping_path: Path
    output_dir: Path
    workspace_id: str
    lakehouse_id: str
    display_name: str = "Generated Fabric Ontology"


def stable_id(value: str) -> str:
    """Return a stable positive signed 64-bit ID as a decimal string."""
    identifier = int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:8], "big") & ID_MAX
    return str(identifier or 1)


def stable_uuid(value: str) -> str:
    return str(uuid.uuid5(UUID_NAMESPACE, value))


def fabric_name(value: str, fallback: str = "Generated") -> str:
    """Preserve a source name when valid, normalizing only for Fabric compatibility."""
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,127}", value):
        return value
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", ascii_value).strip("_-") or fallback
    if not name[0].isalpha():
        name = f"N{name}"
    if len(name) > 128:
        suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
        name = f"{name[:117]}_{suffix}"
    return name


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _table_parts(source_name: str) -> tuple[str, str]:
    parts = source_name.split(".")
    if len(parts) < 2:
        raise ValueError(f"Expected a schema-qualified source table, got '{source_name}'")
    return parts[-2], parts[-1]


def _validate_guid(value: str, name: str) -> None:
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid GUID: '{value}'") from exc


def _unique_name(candidate: str, identity: str, used: set[str]) -> str:
    if candidate not in used:
        used.add(candidate)
        return candidate
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8]
    unique = f"{candidate[:119]}_{suffix}"
    used.add(unique)
    return unique


def _display_property(fields: list[dict[str, Any]], primary_key: list[str]) -> dict[str, Any]:
    preferred_tokens = ("name", "nombre", "description", "descripcion", "title", "titulo")
    for field in fields:
        source_name = field["source_name"].lower()
        if any(token in source_name for token in preferred_tokens):
            return field
    for key_column in primary_key:
        for field in fields:
            if field["source_name"] == key_column:
                return field
    if not fields:
        raise ValueError("An entity type cannot be created without mapped fields")
    return fields[0]


def _write_part(output_dir: Path, relative_path: str, payload: Any) -> dict[str, str]:
    content = _json_bytes(payload)
    destination = output_dir / Path(relative_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return {
        "path": relative_path.replace("\\", "/"),
        "payload": base64.b64encode(content).decode("ascii"),
        "payloadType": "InlineBase64",
    }


def transform(config: TransformConfig) -> dict[str, int]:
    """Generate decoded Fabric parts and an API-ready definition envelope."""
    _validate_guid(config.workspace_id, "workspace_id")
    _validate_guid(config.lakehouse_id, "lakehouse_id")
    mapping = json.loads(config.mapping_path.read_text(encoding="utf-8"))
    graph = Graph().parse(config.ontology_path, format="xml")
    tables = mapping.get("tables", [])
    fields = mapping.get("fields", [])
    relationships = mapping.get("relationships", [])
    if not tables:
        raise ValueError("Mapping contains no tables")

    config.output_dir.mkdir(parents=True, exist_ok=True)
    for generated_dir in ("EntityTypes", "RelationshipTypes"):
        shutil.rmtree(config.output_dir / generated_dir, ignore_errors=True)

    table_by_name = {table["source_name"]: table for table in tables}
    fields_by_table: dict[str, list[dict[str, Any]]] = {name: [] for name in table_by_name}
    field_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    entity_ids: dict[str, str] = {}
    property_ids: dict[str, str] = {}
    allocated_ids: dict[str, str] = {}

    def allocate(identity: str) -> str:
        identifier = stable_id(identity)
        previous = allocated_ids.setdefault(identifier, identity)
        if previous != identity:
            raise ValueError(f"Stable ID collision between '{previous}' and '{identity}'")
        return identifier

    for table in tables:
        class_iri = URIRef(table["class_iri"])
        if (class_iri, RDF.type, OWL.Class) not in graph:
            raise ValueError(f"Mapped table is not an OWL class: {class_iri}")
        entity_ids[table["source_name"]] = allocate(table["class_iri"])

    for field in fields:
        key = (field["source_table"], field["source_name"])
        if key in field_by_key:
            raise ValueError(f"Duplicate field mapping: {key[0]}.{key[1]}")
        if field["source_table"] not in table_by_name:
            raise ValueError(f"Field references an unknown table: {key[0]}")
        property_iri = URIRef(field["property_iri"])
        if (property_iri, RDF.type, OWL.DatatypeProperty) not in graph:
            raise ValueError(f"Mapped field is not an OWL datatype property: {property_iri}")
        expected_domain = URIRef(table_by_name[field["source_table"]]["class_iri"])
        if (property_iri, RDFS.domain, expected_domain) not in graph:
            raise ValueError(f"OWL domain does not match the mapped table for '{property_iri}'")
        field_by_key[key] = field
        fields_by_table[key[0]].append(field)
        property_ids[field["property_iri"]] = allocate(field["property_iri"])

    parts: list[dict[str, str]] = []
    parts.append(
        _write_part(
            config.output_dir,
            ".platform",
            {"metadata": {"type": "Ontology", "displayName": config.display_name}},
        )
    )
    parts.append(_write_part(config.output_dir, "definition.json", {}))

    entity_names: set[str] = set()
    property_names: dict[str, set[str]] = {name: set() for name in table_by_name}
    for table in sorted(tables, key=lambda item: item["class_iri"]):
        source_table = table["source_name"]
        table_fields = sorted(fields_by_table[source_table], key=lambda item: item["property_iri"])
        primary_key = table.get("primary_key") or []
        missing_keys = [column for column in primary_key if (source_table, column) not in field_by_key]
        if missing_keys:
            raise ValueError(f"Primary-key fields missing for '{source_table}': {missing_keys}")
        entity_id = entity_ids[source_table]
        typed_properties: list[dict[str, Any]] = []
        untyped_properties: list[dict[str, Any]] = []
        for field in table_fields:
            property_iri = URIRef(field["property_iri"])
            ranges = sorted(str(value) for value in graph.objects(property_iri, RDFS.range))
            if len(ranges) != 1:
                raise ValueError(f"Expected one RDF range for '{property_iri}', found {ranges}")
            property_name = _unique_name(
                fabric_name(field["source_name"], "Property"),
                field["property_iri"],
                property_names[source_table],
            )
            source_value_type = XSD_VALUE_TYPES.get(ranges[0])
            is_identity = field["source_name"] in primary_key
            value_type = source_value_type
            if is_identity and value_type not in FABRIC_KEY_VALUE_TYPES:
                value_type = "String"
            property_definition: dict[str, Any] = {
                "id": property_ids[field["property_iri"]],
                "name": property_name,
                "valueType": value_type or "Any",
            }
            if value_type:
                custom_attributes = {
                    "sourceColumnName": field["source_name"],
                    "sourceDataType": field.get("data_type", ""),
                    "sourcePropertyIri": field["property_iri"],
                    "sourceRdfDatatype": ranges[0],
                }
                if is_identity and source_value_type != value_type:
                    custom_attributes["fabricIdentityValueType"] = value_type
                property_definition["semanticEnrichment"] = {
                    "description": field.get("business_name") or field["source_name"],
                    "customAttributes": custom_attributes,
                }
            (typed_properties if value_type else untyped_properties).append(property_definition)

        display_field = _display_property(table_fields, primary_key)
        entity_name = _unique_name(
            fabric_name(source_table.rsplit(".", 1)[-1], "Entity"),
            table["class_iri"],
            entity_names,
        )
        entity_definition = {
            "id": entity_id,
            "namespace": FABRIC_NAMESPACE,
            "baseEntityTypeId": None,
            "name": entity_name,
            "entityIdParts": [property_ids[field_by_key[(source_table, key)]["property_iri"]] for key in primary_key],
            "displayNamePropertyId": property_ids[display_field["property_iri"]],
            "namespaceType": FABRIC_NAMESPACE_TYPE,
            "visibility": FABRIC_VISIBILITY,
            "semanticEnrichment": {
                "description": table.get("business_name") or source_table,
                "customAttributes": {
                    "sourceClassIri": table["class_iri"],
                    "sourceTableName": source_table,
                },
            },
            "properties": typed_properties,
            "timeseriesProperties": [],
            "untypedProperties": untyped_properties,
        }
        parts.append(_write_part(config.output_dir, f"EntityTypes/{entity_id}/definition.json", entity_definition))

        source_schema, source_table_name = _table_parts(source_table)
        binding_id = stable_uuid(f"data-binding:{table['class_iri']}:{config.workspace_id}:{config.lakehouse_id}")
        binding = {
            "id": binding_id,
            "dataBindingConfiguration": {
                "dataBindingType": "NonTimeSeries",
                "propertyBindings": [
                    {
                        "sourceColumnName": field["source_name"],
                        "targetPropertyId": property_ids[field["property_iri"]],
                    }
                    for field in table_fields
                ],
                "sourceTableProperties": {
                    "sourceType": "LakehouseTable",
                    "workspaceId": config.workspace_id,
                    "itemId": config.lakehouse_id,
                    "sourceTableName": source_table_name,
                    "sourceSchema": source_schema,
                },
            },
        }
        parts.append(_write_part(config.output_dir, f"EntityTypes/{entity_id}/DataBindings/{binding_id}.json", binding))

    relationship_names: set[str] = set()
    for relationship in sorted(relationships, key=lambda item: item["property_iri"]):
        relationship_iri = URIRef(relationship["property_iri"])
        if (relationship_iri, RDF.type, OWL.ObjectProperty) not in graph:
            raise ValueError(f"Mapped relationship is not an OWL object property: {relationship_iri}")
        source_table = relationship["source_table"]
        target_table = relationship["target_table"]
        expected_domain = URIRef(table_by_name[source_table]["class_iri"])
        expected_range = URIRef(table_by_name[target_table]["class_iri"])
        if (relationship_iri, RDFS.domain, expected_domain) not in graph:
            raise ValueError(f"OWL domain does not match the mapped source for '{relationship_iri}'")
        if (relationship_iri, RDFS.range, expected_range) not in graph:
            raise ValueError(f"OWL range does not match the mapped target for '{relationship_iri}'")
        source_field = field_by_key.get((source_table, relationship["source_column"]))
        target_field = field_by_key.get((target_table, relationship["target_column"]))
        if not source_field or not target_field:
            raise ValueError(f"Relationship has unresolved field mappings: {relationship['constraint']}")
        source_primary_key = table_by_name[source_table].get("primary_key") or []
        if not source_primary_key:
            raise ValueError(f"Relationship source table has no primary key: {source_table}")

        relationship_id = allocate(relationship["property_iri"])
        relationship_name = _unique_name(
            fabric_name(relationship["constraint"], "Relationship"),
            relationship["property_iri"],
            relationship_names,
        )
        relationship_definition = {
            "id": relationship_id,
            "namespace": FABRIC_NAMESPACE,
            "name": relationship_name,
            "namespaceType": FABRIC_NAMESPACE_TYPE,
            "source": {"entityTypeId": entity_ids[source_table]},
            "target": {"entityTypeId": entity_ids[target_table]},
            "semanticEnrichment": {
                "description": relationship.get("business_name") or relationship["constraint"],
                "customAttributes": {
                    "sourceConstraintName": relationship["constraint"],
                    "sourcePropertyIri": relationship["property_iri"],
                },
            },
        }
        parts.append(
            _write_part(
                config.output_dir,
                f"RelationshipTypes/{relationship_id}/definition.json",
                relationship_definition,
            )
        )

        source_schema, source_table_name = _table_parts(source_table)
        contextualization_id = stable_uuid(
            f"contextualization:{relationship['property_iri']}:{config.workspace_id}:{config.lakehouse_id}"
        )
        contextualization = {
            "id": contextualization_id,
            "dataBindingTable": {
                "sourceType": "LakehouseTable",
                "workspaceId": config.workspace_id,
                "itemId": config.lakehouse_id,
                "sourceTableName": source_table_name,
                "sourceSchema": source_schema,
            },
            "sourceKeyRefBindings": [
                {
                    "sourceColumnName": key,
                    "targetPropertyId": property_ids[field_by_key[(source_table, key)]["property_iri"]],
                }
                for key in source_primary_key
            ],
            "targetKeyRefBindings": [
                {
                    "sourceColumnName": relationship["source_column"],
                    "targetPropertyId": property_ids[target_field["property_iri"]],
                }
            ],
        }
        parts.append(
            _write_part(
                config.output_dir,
                f"RelationshipTypes/{relationship_id}/Contextualizations/{contextualization_id}.json",
                contextualization,
            )
        )

    envelope = {"parts": sorted(parts, key=lambda item: item["path"])}
    (config.output_dir / "fabric-definition.json").write_bytes(_json_bytes(envelope))
    return {
        "entity_types": len(tables),
        "properties": len(fields),
        "relationship_types": len(relationships),
        "data_bindings": len(tables),
        "contextualizations": len(relationships),
        "parts": len(parts),
    }