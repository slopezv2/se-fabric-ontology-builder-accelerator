"""Transform canonical RDF/OWL into Microsoft Fabric Ontology definitions."""

from .fabric_definition import TransformConfig, transform

__all__ = ["TransformConfig", "transform"]
