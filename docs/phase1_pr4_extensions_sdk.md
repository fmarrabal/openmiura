# Phase 1 · PR4 · Contratos estables de extensibilidad

Este cambio cierra el bloque **1.4 Contratos de extensibilidad** del roadmap de la fase 1.

## Qué se introduce

Se añade un SDK público mínimo en `openmiura/extensions/sdk/` con contratos estables para:

- tools
- skills
- providers LLM
- channel adapters
- storage backends
- auth providers
- observability exporters

Además se añade:

- `ExtensionManifest` como manifest común y versionado
- `ExtensionLoader` para descubrimiento y carga por `manifest.yaml`
- contextos de ejecución tipados para cada tipo de extensión
- utilidades mínimas de testing para plugins

## Decisiones de diseño

1. **No romper el sistema actual**
   - el cargador existente de skills sigue funcionando
   - el SDK nuevo convive con el legacy

2. **Contrato público, implementación interna desacoplada**
   - una extensión nueva ya no necesita importar módulos privados de `gateway`, `pipeline` o `http_broker`
   - el contrato se apoya en `typing.Protocol` y manifests declarativos

3. **Versionado explícito**
   - `manifest_version`
   - `contract_version`

## Superficie pública nueva

- `openmiura.extensions.loader.ExtensionLoader`
- `openmiura.extensions.sdk.ExtensionManifest`
- `openmiura.extensions.sdk.ToolExtension`
- `openmiura.extensions.sdk.SkillExtension`
- `openmiura.extensions.sdk.LLMProviderExtension`
- `openmiura.extensions.sdk.ChannelAdapterExtension`
- `openmiura.extensions.sdk.StorageBackendExtension`
- `openmiura.extensions.sdk.AuthProviderExtension`
- `openmiura.extensions.sdk.ObservabilityExporterExtension`

## Ejemplo de manifest

```yaml
manifest_version: "1"
contract_version: "1.0"
name: demo_echo
kind: tool
version: "0.1.0"
description: Demo tool for the public SDK
entrypoint: demo_tool.tool:EchoTool
permissions:
  - tools.read
capabilities:
  - echo
```

## Siguiente paso del roadmap

Con esto queda preparado el terreno para seguir en fase 1 con:

- consolidación del broker HTTP v1
- limpieza progresiva de interfaces legacy
- preparación de la fase 2 enterprise sin depender de imports privados para extensiones
