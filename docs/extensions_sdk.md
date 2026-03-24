# SDK oficial de extensiones

## Flujo recomendado

1. Crear scaffold:
   - `openmiura create tool my-tool`
   - `openmiura create skill my-skill`
   - `openmiura create provider my-provider`
   - `openmiura create channel my-channel`
   - `openmiura create auth my-auth`
   - `openmiura create storage my-storage`
   - `openmiura create workflow my-workflow`
2. Validar manifiesto:
   - `openmiura sdk validate-manifest ./my-tool/manifest.yaml`
3. Ejecutar harness contractual:
   - `openmiura sdk test-extension ./my-tool`
4. Publicar en el registry privado:
   - `openmiura registry publish ./my-tool --root ./registry --namespace demo`
5. Verificar integridad firmada:
   - `openmiura registry verify my-tool 0.1.0 --root ./registry --namespace demo`
6. Aplicar política de instalación del tenant:
   - `openmiura registry policy-set demo --root ./registry --allowed-namespace demo`
7. Instalar:
   - `openmiura registry install my-tool --root ./registry --namespace demo --tenant demo`

## Comandos útiles

- `openmiura sdk quickstart --kind tool`
- `openmiura sdk validate-manifest <path>`
- `openmiura sdk test-extension <path>`

## Qué valida el harness

- estructura y campos del `manifest.yaml`
- compatibilidad de contrato y versión de openMiura
- coherencia entre `entrypoint` y objeto exportado
- smoke test por tipo de extensión
- serialización JSON del smoke result
- señales de empaquetado mínimas (`README.md`, `CHANGELOG.md`, `tests/test_smoke.py`)
- patrones inseguros evidentes (`os.system`, `shell=True`, `eval`, `exec`)

## Recomendaciones DX

- mantener `README.md` y `CHANGELOG.md` al día
- declarar `compatibility.min_openmiura_version`
- no publicar sin pasar `sdk test-extension`
- añadir al menos un smoke test representativo
