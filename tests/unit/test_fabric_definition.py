import base64
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from rdflib import Graph, OWL, RDF, RDFS, XSD, URIRef

from transform import TransformConfig, transform
from transform.fabric_definition import fabric_name


class FabricDefinitionTests(TestCase):
    def test_fabric_name_only_normalizes_incompatible_characters(self) -> None:
        self.assertEqual(fabric_name("detalle_orden"), "detalle_orden")
        self.assertEqual(fabric_name("Código-Año"), "Codigo-Ano")

    def test_transform_emits_deterministic_bound_definition(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            ontology_path = root / "ontology.owl"
            mapping_path = root / "mapping.json"
            output_dir = root / "definition"
            customer_iri = "https://example.test/table/catalog/schema/customer"
            order_iri = "https://example.test/table/catalog/schema/order"
            customer_id_iri = "https://example.test/property/customer/id"
            order_id_iri = "https://example.test/property/order/id"
            order_customer_iri = "https://example.test/property/order/customer_id"
            relationship_iri = "https://example.test/relationship/order/customer"

            graph = Graph()
            for class_iri in (customer_iri, order_iri):
                graph.add((URIRef(class_iri), RDF.type, OWL.Class))
            for property_iri, domain in (
                (customer_id_iri, customer_iri),
                (order_id_iri, order_iri),
                (order_customer_iri, order_iri),
            ):
                graph.add((URIRef(property_iri), RDF.type, OWL.DatatypeProperty))
                graph.add((URIRef(property_iri), RDFS.domain, URIRef(domain)))
                graph.add((URIRef(property_iri), RDFS.range, XSD.date if property_iri == customer_id_iri else XSD.string))
            graph.add((URIRef(relationship_iri), RDF.type, OWL.ObjectProperty))
            graph.add((URIRef(relationship_iri), RDFS.domain, URIRef(order_iri)))
            graph.add((URIRef(relationship_iri), RDFS.range, URIRef(customer_iri)))
            graph.serialize(ontology_path, format="xml")

            mapping = {
                "tables": [
                    {"source_name": "catalog.schema.customer", "business_name": "Customer", "class_iri": customer_iri, "primary_key": ["id"]},
                    {"source_name": "catalog.schema.order", "business_name": "Order", "class_iri": order_iri, "primary_key": ["id"]},
                ],
                "fields": [
                    {"source_table": "catalog.schema.customer", "source_name": "id", "business_name": "Customer ID", "property_iri": customer_id_iri, "data_type": "date"},
                    {"source_table": "catalog.schema.order", "source_name": "id", "business_name": "Order ID", "property_iri": order_id_iri, "data_type": "string"},
                    {"source_table": "catalog.schema.order", "source_name": "customer_id", "business_name": "Customer ID", "property_iri": order_customer_iri, "data_type": "string"},
                ],
                "relationships": [
                    {
                        "constraint": "fk_order_customer",
                        "business_name": "Order belongs to Customer",
                        "source_table": "catalog.schema.order",
                        "source_column": "customer_id",
                        "target_table": "catalog.schema.customer",
                        "target_column": "id",
                        "property_iri": relationship_iri,
                    }
                ],
            }
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            config = TransformConfig(
                ontology_path=ontology_path,
                mapping_path=mapping_path,
                output_dir=output_dir,
                workspace_id="11111111-1111-1111-1111-111111111111",
                lakehouse_id="22222222-2222-2222-2222-222222222222",
                display_name="Test Ontology",
            )

            first_counts = transform(config)
            first_bundle = (output_dir / "fabric-definition.json").read_bytes()
            second_counts = transform(config)
            second_bundle = (output_dir / "fabric-definition.json").read_bytes()

            self.assertEqual(first_counts, second_counts)
            self.assertEqual(first_counts["parts"], 8)
            self.assertEqual(first_bundle, second_bundle)
            envelope = json.loads(first_bundle)
            self.assertEqual(len({part["path"] for part in envelope["parts"]}), 8)
            for part in envelope["parts"]:
                decoded = base64.b64decode(part["payload"])
                self.assertEqual(decoded, (output_dir / part["path"]).read_bytes())

            entity_files = sorted(output_dir.glob("EntityTypes/*/definition.json"))
            self.assertEqual(len(entity_files), 2)
            for entity_file in entity_files:
                entity = json.loads(entity_file.read_text(encoding="utf-8"))
                self.assertRegex(entity["name"], re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,127}$"))
                property_ids = {item["id"] for item in entity["properties"]}
                self.assertTrue(set(entity["entityIdParts"]).issubset(property_ids))
                key_properties = [item for item in entity["properties"] if item["id"] in entity["entityIdParts"]]
                self.assertTrue(all(item["valueType"] in {"BigInt", "String"} for item in key_properties))

            customer_entity = next(
                json.loads(path.read_text(encoding="utf-8"))
                for path in entity_files
                if json.loads(path.read_text(encoding="utf-8"))["name"] == "customer"
            )
            customer_key = next(item for item in customer_entity["properties"] if item["id"] in customer_entity["entityIdParts"])
            self.assertEqual(customer_key["valueType"], "String")
            self.assertEqual(customer_key["semanticEnrichment"]["customAttributes"]["sourceRdfDatatype"], str(XSD.date))

            contextualization_file = next(output_dir.glob("RelationshipTypes/*/Contextualizations/*.json"))
            contextualization = json.loads(contextualization_file.read_text(encoding="utf-8"))
            binding_file = next(output_dir.glob("EntityTypes/*/DataBindings/*.json"))
            binding = json.loads(binding_file.read_text(encoding="utf-8"))
            self.assertEqual(next(iter(binding["dataBindingConfiguration"]["sourceTableProperties"])), "sourceType")
            self.assertEqual(next(iter(contextualization["dataBindingTable"])), "sourceType")
            self.assertEqual(contextualization["dataBindingTable"]["sourceTableName"], "order")
            self.assertEqual(contextualization["sourceKeyRefBindings"][0]["sourceColumnName"], "id")
            self.assertEqual(contextualization["targetKeyRefBindings"][0]["sourceColumnName"], "customer_id")

    def test_transform_preserves_spanish_source_names_over_english_business_names(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            ontology_path = root / "ontology.owl"
            mapping_path = root / "mapping.json"
            output_dir = root / "definition"
            class_iri = "https://example.test/table/catalog/schema/almacenes"
            property_iri = "https://example.test/property/almacenes/codigo_almacen"

            graph = Graph()
            graph.add((URIRef(class_iri), RDF.type, OWL.Class))
            graph.add((URIRef(property_iri), RDF.type, OWL.DatatypeProperty))
            graph.add((URIRef(property_iri), RDFS.domain, URIRef(class_iri)))
            graph.add((URIRef(property_iri), RDFS.range, XSD.string))
            graph.serialize(ontology_path, format="xml")

            mapping_path.write_text(
                json.dumps(
                    {
                        "tables": [
                            {
                                "source_name": "catalog.schema.almacenes",
                                "business_name": "Warehouses",
                                "class_iri": class_iri,
                                "primary_key": ["codigo_almacen"],
                            }
                        ],
                        "fields": [
                            {
                                "source_table": "catalog.schema.almacenes",
                                "source_name": "codigo_almacen",
                                "business_name": "Warehouse Code",
                                "property_iri": property_iri,
                                "data_type": "string",
                            }
                        ],
                        "relationships": [],
                    }
                ),
                encoding="utf-8",
            )

            transform(
                TransformConfig(
                    ontology_path=ontology_path,
                    mapping_path=mapping_path,
                    output_dir=output_dir,
                    workspace_id="11111111-1111-1111-1111-111111111111",
                    lakehouse_id="22222222-2222-2222-2222-222222222222",
                )
            )

            entity_path = next(output_dir.glob("EntityTypes/*/definition.json"))
            entity = json.loads(entity_path.read_text(encoding="utf-8"))
            self.assertEqual(entity["name"], "almacenes")
            self.assertEqual(entity["properties"][0]["name"], "codigo_almacen")
            self.assertEqual(entity["semanticEnrichment"]["description"], "Warehouses")
            self.assertEqual(entity["properties"][0]["semanticEnrichment"]["description"], "Warehouse Code")