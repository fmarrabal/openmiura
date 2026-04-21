// Tiny OpenClaw Runtime console
(() => {
  const requiredIds = [
    'tinyRuntimeSelect',
    'tinyRefreshBtn',
    'tinyLoadRuntimeBtn',
    'tinyHealthBtn',
    'tinyDispatchBtn',
    'tinyRefreshDispatchesBtn',
    'tinyRefreshTimelineBtn',
    'tinyOverview',
    'tinyStatusBox',
    'tinyDispatchBox',
    'tinyMetadataBox',
    'tinyLlmCards',
    'tinySkillsList',
    'tinyBridgeList',
    'tinyDispatchList',
    'tinyTimelineList',
    'tinyRuntimeHint',
    'tinyMessageInput',
    'tinySessionId',
    'tinyAgentId',
    'tinyDryRunToggle',
    'tinyLlmModeBadge',
    'tinyCopyMetadataBtn',
    'tinyWizardRefreshBtn',
    'tinyWizardTemplateSelect',
    'tinyWizardTemplateName',
    'tinyWizardTemplateCategory',
    'tinyWizardRefreshCertificateProfilesBtn',
    'tinyWizardLoadCertificateProfileBtn',
    'tinyWizardIssueCertificateProfileBtn',
    'tinyWizardRotateCertificateProfileBtn',
    'tinyWizardRevokeCertificateProfileBtn',
    'tinyWizardCertificateProfileSelect',
    'tinyWizardCertificateProfileName',
    'tinyWizardCertificateValidityDays',
    'tinyWizardSyncTrustStoreOnCertificateLifecycle',
    'tinyWizardCertificateProfileBox',
    'tinyWizardTemplateLibrary',
    'tinyWizardLoadTemplateBtn',
    'tinyWizardSignPackage',
    'tinyWizardRequireSignature',
    'tinyWizardIncludeOrgCertificate',
    'tinyWizardRequireCertificate',
    'tinyWizardAllowRotatedSigners',
    'tinyWizardSigningProvider',
    'tinyWizardSigningKeyId',
    'tinyWizardOrganizationId',
    'tinyWizardOrganizationName',
    'tinyWizardOrganizationUnit',
    'tinyWizardCertificateRole',
    'tinyWizardRootKeyId',
    'tinyWizardCertificateKeyEpoch',
    'tinyWizardPreviousSigningKeyIds',
    'tinyWizardPreviousSigningFingerprints',
    'tinyWizardTrustedSignerFingerprints',
    'tinyWizardTrustedOrganizationIds',
    'tinyWizardTrustedOrgRootFingerprints',
    'tinyWizardSaveTemplateBtn',
    'tinyWizardCloneTemplateBtn',
    'tinyWizardUpdateTemplateBtn',
    'tinyWizardDeleteTemplateBtn',
    'tinyWizardPreviewBtn',
    'tinyWizardTestConnectionBtn',
    'tinyWizardRegisterBtn',
    'tinyWizardCopyPreviewBtn',
    'tinyWizardHint',
    'tinyWizardName',
    'tinyWizardTransport',
    'tinyWizardBaseUrl',
    'tinyWizardPolicyPack',
    'tinyWizardAuthSecretRef',
    'tinyWizardTenantId',
    'tinyWizardWorkspaceId',
    'tinyWizardEnvironment',
    'tinyWizardAllowedAgents',
    'tinyWizardSkills',
    'tinyWizardLlmProvider',
    'tinyWizardLlmModel',
    'tinyWizardLlmBaseUrl',
    'tinyWizardApiStyle',
    'tinyWizardStateStorage',
    'tinyWizardSessionBridge',
    'tinyWizardEventBridge',
    'tinyWizardStateBridge',
    'tinyWizardChatProbeEnabled',
    'tinyWizardChatProbeMode',
    'tinyWizardChatProbePrompt',
    'tinyWizardChatProbeExpectedContent',
    'tinyWizardCapabilities',
    'tinyWizardProviderNotes',
    'tinyWizardTrustStoreHierarchy',
    'tinyWizardPreviewBox',
    'tinyWizardResultBox',
  ];

  const $ = (id) => document.getElementById(id);
  if (!requiredIds.every((id) => $(id))) return;

  const tinyState = {
    runtimes: [],
    runtimeId: '',
    detail: null,
    timeline: [],
    wizard: {
      loaded: false,
      policyPacks: [],
      providers: [],
      signingProviders: [],
      defaults: {},
      templates: [],
      templateCategories: [],
      lastValidation: null,
      importApprovals: [],
      importApprovalsSummary: {},
      trustDecisions: [],
      trustDecisionsSummary: {},
      certificateProfiles: [],
      certificateProfilesSummary: {},
      selectedTrustStoreLevel: 'environment',
    },
  };

  const pretty = (value) => JSON.stringify(value, null, 2);

  function brokerBase() {
    const fallback = `${location.origin}/broker`;
    return String(localStorage.getItem('openmiura.baseUrl') || fallback).replace(/\/$/, '');
  }

  function authHeaders() {
    const stored = String(localStorage.getItem('openmiura.token') || '').trim();
    const field = String(($('token') && $('token').value) || '').trim();
    const token = stored || field;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  async function api(path, options = {}) {
    const headers = {
      ...authHeaders(),
      ...(options.headers || {}),
    };
    const config = {
      method: options.method || 'GET',
      headers,
      body: options.body,
    };
    const response = await fetch(`${brokerBase()}${path}`, config);
    const text = await response.text();
    let payload = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      payload = { raw: text };
    }
    if (!response.ok) {
      const detail = payload.detail || payload.error || payload.raw || `HTTP ${response.status}`;
      throw new Error(String(detail));
    }
    return payload;
  }

  function setStatus(message, tone = 'muted') {
    const box = $('tinyStatusBox');
    box.classList.remove('ok', 'danger', 'muted');
    box.classList.add(tone);
    box.textContent = String(message || 'Ready');
  }

  function renderEmpty(containerId, message) {
    $(containerId).innerHTML = `<div class="tiny-empty">${message}</div>`;
  }

  function parseCsv(value) {
    return String(value || '')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function isTinyRuntimeCandidate(item) {
    const runtime = item || {};
    const metadata = runtime.metadata || {};
    const summary = runtime.runtime_summary || {};
    const summaryMeta = summary.metadata || {};
    const seed = [
      runtime.name,
      metadata.kind,
      metadata.runtime_class,
      metadata.policy_pack,
      summaryMeta.kind,
      summaryMeta.runtime_class,
      summaryMeta.policy_pack,
    ].join(' ').toLowerCase();
    return (
      metadata.kind === 'tiny_openclaw'
      || summaryMeta.kind === 'tiny_openclaw'
      || seed.includes('tiny')
      || seed.includes('openclaw')
      || seed.includes('local')
    );
  }

  function runtimeScope(runtime) {
    const scope = ((runtime || {}).runtime_summary || {}).scope || {};
    return [scope.tenant_id, scope.workspace_id, scope.environment].filter(Boolean).join(' / ') || 'global';
  }

  function normalizeLocalLlm(detail) {
    const runtime = (detail || {}).runtime || {};
    const metadata = runtime.metadata || {};
    const summaryMeta = (((detail || {}).runtime_summary || {}).metadata || {});
    const llm = metadata.local_llm || metadata.llm || metadata.llm_profile || metadata.model_profile || {};
    const labels = summaryMeta.labels || {};
    return {
      mode: llm.mode || metadata.local_llm_mode || labels.local_llm_mode || (llm.base_url || metadata.base_url ? 'local' : 'managed'),
      provider: llm.provider || metadata.provider || metadata.llm_provider || labels.llm_provider || 'unknown',
      model: llm.model || metadata.model || metadata.llm_model || labels.llm_model || 'not declared',
      base_url: llm.base_url || metadata.base_url || metadata.llm_base_url || labels.llm_base_url || 'not declared',
      api_style: llm.api_style || metadata.api_style || labels.api_style || 'openai-compatible',
      embedding_model: llm.embedding_model || metadata.embedding_model || labels.embedding_model || 'n/a',
      notes: llm.notes || metadata.notes || '',
    };
  }

  function normalizeSkills(detail) {
    const runtime = (detail || {}).runtime || {};
    const summary = (detail || {}).runtime_summary || {};
    const metadata = runtime.metadata || {};
    const seed = [];
    const skillCatalog = metadata.skill_catalog || metadata.skills || metadata.skill_names || [];
    if (Array.isArray(skillCatalog)) seed.push(...skillCatalog);
    if (Array.isArray(runtime.capabilities)) seed.push(...runtime.capabilities);
    if (Array.isArray(summary.allowed_actions)) seed.push(...summary.allowed_actions.map((name) => `action:${name}`));
    return [...new Set(seed.map((item) => String(item || '').trim()).filter(Boolean))].sort();
  }

  function normalizeBridges(detail) {
    const runtime = (detail || {}).runtime || {};
    const summary = (detail || {}).runtime_summary || {};
    const metadata = runtime.metadata || {};
    const bridges = [];
    const sessionBridge = summary.session_bridge || metadata.session_bridge || {};
    const eventBridge = summary.event_bridge || metadata.event_bridge || {};
    const stateBridge = metadata.state_bridge || metadata.memory_bridge || {};

    bridges.push({
      title: 'Session bridge',
      body: sessionBridge.enabled ? `enabled · ${sessionBridge.workspace_connection || 'workspace binding not declared'}` : 'disabled',
    });
    bridges.push({
      title: 'Event bridge',
      body: eventBridge.accepted_event_types ? `${(eventBridge.accepted_event_types || []).length} accepted event types` : (sessionBridge.event_bridge_enabled ? 'enabled' : 'not declared'),
    });
    bridges.push({
      title: 'State bridge',
      body: stateBridge.enabled ? `enabled · ${stateBridge.storage || stateBridge.backend || 'state sync active'}` : 'local-only / not declared',
    });
    return bridges;
  }

  function overviewItems(detail) {
    const runtime = (detail || {}).runtime || {};
    const summary = (detail || {}).runtime_summary || {};
    const llm = normalizeLocalLlm(detail);
    const health = (detail || {}).health || {};
    const dispatchCounts = (detail || {}).dispatch_summary || {};
    const activeCount = Object.entries(dispatchCounts)
      .filter(([status]) => ['requested', 'accepted', 'queued', 'running'].includes(status))
      .reduce((acc, [, count]) => acc + Number(count || 0), 0);
    return [
      { label: 'Health', value: health.status || 'unknown', detail: health.stale ? 'stale' : 'fresh' },
      { label: 'Transport', value: runtime.transport || 'n/a', detail: runtime.base_url || '' },
      { label: 'Policy pack', value: ((summary.metadata || {}).policy_pack || 'generic'), detail: ((summary.metadata || {}).runtime_class || '') },
      { label: 'Local model', value: llm.model, detail: llm.provider },
      { label: 'Scope', value: runtimeScope(detail), detail: runtime.runtime_id || '' },
      { label: 'Active runs', value: String(activeCount), detail: `${Object.keys(dispatchCounts).length} states seen` },
    ];
  }

  function renderOverview(detail) {
    const items = overviewItems(detail);
    $('tinyOverview').innerHTML = items.map((item) => `
      <div class="overview-item">
        <div class="muted">${item.label}</div>
        <strong>${item.value}</strong>
        <small>${item.detail || ''}</small>
      </div>
    `).join('');
  }

  function renderLocalLlm(detail) {
    const llm = normalizeLocalLlm(detail);
    $('tinyLlmModeBadge').textContent = String(llm.mode || 'unknown');
    const cards = [
      { title: 'Provider', text: llm.provider },
      { title: 'Model', text: llm.model },
      { title: 'Endpoint', text: llm.base_url },
      { title: 'API style', text: llm.api_style },
      { title: 'Embedding model', text: llm.embedding_model },
      { title: 'Notes', text: llm.notes || 'No extra notes declared.' },
    ];
    $('tinyLlmCards').innerHTML = cards.map((item) => `
      <div class="card tiny-item">
        <h4>${item.title}</h4>
        <p>${item.text}</p>
      </div>
    `).join('');
  }

  function renderSimpleList(containerId, items, emptyMessage) {
    if (!items.length) {
      renderEmpty(containerId, emptyMessage);
      return;
    }
    $(containerId).innerHTML = items.map((item) => `
      <div class="card tiny-item">
        <h4>${item.title || item}</h4>
        ${item.body ? `<p>${item.body}</p>` : ''}
      </div>
    `).join('');
  }

  function renderDispatches(detail) {
    const dispatches = (detail || {}).dispatches || [];
    if (!dispatches.length) {
      renderEmpty('tinyDispatchList', 'No dispatches recorded for this runtime yet.');
      return;
    }
    $('tinyDispatchList').innerHTML = dispatches.map((item) => `
      <div class="card">
        <div class="row between wrap">
          <strong>${item.action || 'dispatch'}</strong>
          <span class="badge">${item.canonical_status || item.status || 'unknown'}</span>
        </div>
        <small>${item.dispatch_id || ''}</small>
        <small>session: ${item.session_id || 'n/a'} · attempts: ${item.attempt_count || 0}</small>
      </div>
    `).join('');
  }

  function renderTimeline(items) {
    if (!items.length) {
      renderEmpty('tinyTimelineList', 'No runtime timeline entries yet.');
      return;
    }
    $('tinyTimelineList').innerHTML = items.map((item) => `
      <div class="card">
        <div class="row between wrap">
          <strong>${item.action || item.event_type || item.kind || 'event'}</strong>
          <span class="badge">${item.event_status || item.kind || 'runtime'}</span>
        </div>
        <small>${item.dispatch_id || item.session_id || ''}</small>
        <small>${item.ts || ''}</small>
      </div>
    `).join('');
  }

  function populateRuntimeSelect(items) {
    const select = $('tinyRuntimeSelect');
    select.innerHTML = '';
    if (!items.length) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = 'No governed runtimes available';
      select.appendChild(option);
      return;
    }
    items.forEach((item) => {
      const option = document.createElement('option');
      option.value = item.runtime_id;
      option.textContent = `${item.name} · ${runtimeScope({ runtime_summary: { scope: { tenant_id: item.tenant_id, workspace_id: item.workspace_id, environment: item.environment } } })}`;
      select.appendChild(option);
    });
    if (tinyState.runtimeId) select.value = tinyState.runtimeId;
  }

  function selectedPolicyPack() {
    const value = $('tinyWizardPolicyPack').value;
    return tinyState.wizard.policyPacks.find((item) => item.pack_id === value) || null;
  }

  function selectedProvider() {
    const value = $('tinyWizardLlmProvider').value;
    return tinyState.wizard.providers.find((item) => item.provider_id === value) || null;
  }

  function selectedSigningProvider() {
    const value = $('tinyWizardSigningProvider').value;
    return (tinyState.wizard.signingProviders || []).find((item) => item.provider_id === value) || null;
  }

  function signingDefaults() {
    const defaults = ((tinyState.wizard.defaults || {}).template_exchange_signing) || {};
    const org = defaults.organizational_certificate || {};
    return {
      signPackage: defaults.sign_package !== false,
      provider: defaults.provider || 'local-ed25519',
      keyId: defaults.key_id || 'tiny-runtime-template-package',
      requireSignatureOnImport: defaults.require_signature_on_import !== false,
      trustedSignerFingerprints: Array.isArray(defaults.trusted_signer_fingerprints) ? defaults.trusted_signer_fingerprints : [],
      includeOrgCertificate: org.include_on_export !== false,
      requireCertificateOnImport: org.require_on_import !== false,
      organizationId: org.organization_id || 'openmiura-local',
      organizationName: org.organization_name || 'OpenMiura Local Trust',
      organizationUnit: org.organization_unit || 'Tiny Runtime Templates',
      certificateRole: org.certificate_role || 'template-package-signer',
      rootKeyId: org.root_key_id || 'openmiura-org-root',
      certificateKeyEpoch: Number(org.certificate_key_epoch || 1),
      previousSigningKeyIds: Array.isArray(org.previous_signing_key_ids) ? org.previous_signing_key_ids : [],
      previousSigningFingerprints: Array.isArray(org.previous_signing_fingerprints) ? org.previous_signing_fingerprints : [],
      trustedOrganizationIds: Array.isArray(org.trusted_organization_ids) ? org.trusted_organization_ids : [],
      trustedOrgRootFingerprints: Array.isArray(org.trusted_org_root_fingerprints) ? org.trusted_org_root_fingerprints : [],
      allowRotatedSigners: org.allow_rotated_signers !== false,
    };
  }

  function certificateLifecycleDefaults() {
    const defaults = ((tinyState.wizard.defaults || {}).certificate_lifecycle) || {};
    return {
      certificateValidityDays: Number(defaults.certificate_validity_days || 365),
      syncTrustStore: defaults.sync_trust_store !== false,
      defaultScopeLevel: defaults.default_scope_level || 'environment',
    };
  }

  function populateCertificateProfileOptions() {
    const select = $('tinyWizardCertificateProfileSelect');
    const profiles = tinyState.wizard.certificateProfiles || [];
    select.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = profiles.length ? 'Choose a certificate profile…' : 'No certificate profiles yet';
    select.appendChild(placeholder);
    profiles.forEach((item) => {
      const option = document.createElement('option');
      option.value = item.profile_id || '';
      const summary = item.summary || {};
      option.textContent = `${item.profile_name || 'profile'} · ${summary.organization_id || 'org'} · epoch ${summary.certificate_key_epoch || 1} · ${item.lifecycle_status || 'active'}`;
      select.appendChild(option);
    });
    const selected = profiles.find((item) => item.profile_id === select.value) || profiles[0] || null;
    $('tinyWizardCertificateProfileBox').textContent = pretty(selected || {});
  }

  function selectedCertificateProfile() {
    const value = $('tinyWizardCertificateProfileSelect').value;
    return (tinyState.wizard.certificateProfiles || []).find((item) => item.profile_id === value) || null;
  }

  function applyCertificateProfileToWizard(entry) {
    if (!entry) return;
    const profile = entry.profile || {};
    $('tinyWizardCertificateProfileName').value = entry.profile_name || profile.profile_name || '';
    $('tinyWizardSigningProvider').value = profile.signing_provider || $('tinyWizardSigningProvider').value || 'local-ed25519';
    $('tinyWizardSigningKeyId').value = profile.current_signing_key_id || $('tinyWizardSigningKeyId').value;
    $('tinyWizardOrganizationId').value = profile.organization_id || $('tinyWizardOrganizationId').value;
    $('tinyWizardOrganizationName').value = profile.organization_name || $('tinyWizardOrganizationName').value;
    $('tinyWizardOrganizationUnit').value = profile.organization_unit || $('tinyWizardOrganizationUnit').value;
    $('tinyWizardCertificateRole').value = profile.certificate_role || $('tinyWizardCertificateRole').value;
    $('tinyWizardRootKeyId').value = profile.root_key_id || $('tinyWizardRootKeyId').value;
    $('tinyWizardCertificateKeyEpoch').value = String(profile.certificate_key_epoch || $('tinyWizardCertificateKeyEpoch').value || 1);
    $('tinyWizardCertificateValidityDays').value = String(profile.certificate_validity_days || $('tinyWizardCertificateValidityDays').value || certificateLifecycleDefaults().certificateValidityDays);
    $('tinyWizardPreviousSigningKeyIds').value = (profile.previous_signing_key_ids || []).join(', ');
    $('tinyWizardPreviousSigningFingerprints').value = (profile.previous_signing_fingerprints || []).join(', ');
    $('tinyWizardCertificateProfileBox').textContent = pretty(entry);
    updateWizardPreview();
  }

  function trustStoreDefaults() {
    const defaults = ((tinyState.wizard.defaults || {}).template_exchange_trust_store) || (tinyState.wizard.trustStore || {}) || {};
    const denylist = defaults.denylist || {};
    const crl = defaults.crl || {};
    return {
      requireSignature: defaults.require_signature !== false,
      requireCertificate: defaults.require_certificate !== false,
      allowRotatedSigners: defaults.allow_rotated_signers !== false,
      trustedSignerFingerprints: Array.isArray(defaults.trusted_signer_fingerprints) ? defaults.trusted_signer_fingerprints : [],
      trustedOrganizationIds: Array.isArray(defaults.trusted_organization_ids) ? defaults.trusted_organization_ids : [],
      trustedOrgRootFingerprints: Array.isArray(defaults.trusted_org_root_fingerprints) ? defaults.trusted_org_root_fingerprints : [],
      deniedPackageHashes: Array.isArray(denylist.package_sha256) ? denylist.package_sha256 : [],
      revokedSignerFingerprints: Array.isArray(denylist.signer_fingerprints) ? denylist.signer_fingerprints : [],
      revokedSigningKeyIds: Array.isArray(denylist.signing_key_ids) ? denylist.signing_key_ids : [],
      revokedOrganizationIds: Array.isArray(denylist.organization_ids) ? denylist.organization_ids : [],
      revokedOrgRootFingerprints: Array.isArray(denylist.org_root_fingerprints) ? denylist.org_root_fingerprints : [],
      revokedCertificateFingerprints: Array.isArray(denylist.certificate_fingerprints) ? denylist.certificate_fingerprints : [],
      revokedCertificateIds: Array.isArray(denylist.certificate_ids) ? denylist.certificate_ids : [],
      revokedCertificates: Array.isArray(crl.revoked_certificates) ? crl.revoked_certificates : [],
    };
  }

  function parseCrlEntries(raw) {
    const text = String(raw || '').trim();
    if (!text) return [];
    try {
      const parsed = JSON.parse(text);
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  }

  function trustStorePayload() {
    const defaults = trustStoreDefaults();
    return {
      require_signature: !!$('tinyWizardRequireSignature').checked,
      require_certificate: !!$('tinyWizardRequireCertificate').checked,
      allow_rotated_signers: !!$('tinyWizardAllowRotatedSigners').checked,
      trusted_signer_fingerprints: parseCsv($('tinyWizardTrustedSignerFingerprints').value).map((item) => item.toLowerCase()),
      trusted_organization_ids: parseCsv($('tinyWizardTrustedOrganizationIds').value),
      trusted_org_root_fingerprints: parseCsv($('tinyWizardTrustedOrgRootFingerprints').value).map((item) => item.toLowerCase()),
      denylist: {
        package_sha256: parseCsv($('tinyWizardDeniedPackageHashes').value).map((item) => item.toLowerCase()),
        signer_fingerprints: parseCsv($('tinyWizardRevokedSignerFingerprints').value).map((item) => item.toLowerCase()),
        signing_key_ids: parseCsv($('tinyWizardRevokedSigningKeyIds').value),
        organization_ids: parseCsv($('tinyWizardRevokedOrganizationIds').value),
        org_root_fingerprints: parseCsv($('tinyWizardRevokedOrgRootFingerprints').value).map((item) => item.toLowerCase()),
        certificate_fingerprints: parseCsv($('tinyWizardRevokedCertificateFingerprints').value).map((item) => item.toLowerCase()),
        certificate_ids: parseCsv($('tinyWizardRevokedCertificateIds').value),
      },
      crl: {
        revoked_certificates: parseCrlEntries($('tinyWizardCertificateRevocationList').value).length
          ? parseCrlEntries($('tinyWizardCertificateRevocationList').value)
          : defaults.revokedCertificates,
      },
    };
  }

  function renderTrustStoreSummary() {
    const summary = tinyState.wizard.trustStoreSummary || {};
    const effective = tinyState.wizard.effectiveTrustStoreSummary || {};
    const hierarchy = Array.isArray(tinyState.wizard.trustStoreHierarchy) ? tinyState.wizard.trustStoreHierarchy : [];
    const configuredLevels = hierarchy.filter((item) => item && item.configured).map((item) => item.level || item.scope_label || 'scope');
    const level = tinyState.wizard.selectedTrustStoreLevel || 'environment';
    $('tinyWizardTrustStoreSummary').textContent = `Configured ${level} trust policy · trusted signers ${summary.trusted_signer_count || 0}, trusted orgs ${summary.trusted_organization_count || 0}, trusted roots ${summary.trusted_org_root_count || 0}, denylisted packages ${summary.denylisted_package_count || 0}, CRL entries ${summary.crl_entry_count || 0}. Effective inherited trust · layers ${effective.configured_layer_count || 0}, trusted signers ${effective.trusted_signer_count || 0}, trusted orgs ${effective.trusted_organization_count || 0}, trusted roots ${effective.trusted_org_root_count || 0}${configuredLevels.length ? ` (${configuredLevels.join(' → ')})` : ''}.`;
    $('tinyWizardTrustStoreHierarchy').textContent = pretty({
      selected_level: level,
      local_scope: summary.scope_label || runtimeScope({ runtime_summary: { scope: { tenant_id: summary.tenant_id, workspace_id: summary.workspace_id, environment: summary.environment } } }),
      effective_scope: effective.scope_label || runtimeScope({ runtime_summary: { scope: { tenant_id: effective.tenant_id, workspace_id: effective.workspace_id, environment: effective.environment } } }),
      effective_layers: configuredLevels,
      hierarchy: hierarchy.map((item) => ({
        level: item.level,
        scope_label: item.scope_label,
        configured: !!item.configured,
        trust_store_id: ((item.summary || {}).trust_store_id) || '',
        trusted_signer_count: ((item.summary || {}).trusted_signer_count) || 0,
        trusted_organization_count: ((item.summary || {}).trusted_organization_count) || 0,
        trusted_org_root_count: ((item.summary || {}).trusted_org_root_count) || 0,
        denylisted_package_count: ((item.summary || {}).denylisted_package_count) || 0,
        crl_entry_count: ((item.summary || {}).crl_entry_count) || 0,
      })),
    });
  }

  function renderSigningProviders() {
    const select = $('tinyWizardSigningProvider');
    const current = select.value;
    const providers = tinyState.wizard.signingProviders || [];
    select.innerHTML = '';
    (providers.length ? providers : [{ provider_id: 'local-ed25519', label: 'Local Ed25519 key' }]).forEach((item) => {
      const option = document.createElement('option');
      option.value = item.provider_id || 'local-ed25519';
      option.textContent = item.label || item.provider_id || 'local-ed25519';
      select.appendChild(option);
    });
    if (providers.some((item) => item.provider_id === current)) {
      select.value = current;
    } else if (!select.value) {
      select.value = signingDefaults().provider;
    }
  }

  function currentProbeDefaults() {
    const defaults = ((((tinyState.wizard.defaults || {}).default_validation || {}).chat_completion_probe) || {});
    return {
      mode: defaults.mode || 'smoke',
      smokePrompt: defaults.smoke_prompt || 'Reply with the single word pong.',
      smokeExpectedContent: defaults.smoke_expected_content || 'pong',
      customPrompt: defaults.prompt || 'Reply with: local runtime ready',
      customExpectedContent: defaults.expected_content || 'local runtime ready',
      maxTokens: Number(defaults.max_tokens || 24),
      temperature: Number(defaults.temperature || 0),
    };
  }

  function syncProbeModeUi() {
    const provider = selectedProvider() || {};
    const defaults = currentProbeDefaults();
    const mode = $('tinyWizardChatProbeMode').value || defaults.mode || 'smoke';
    const promptInput = $('tinyWizardChatProbePrompt');
    const expectedInput = $('tinyWizardChatProbeExpectedContent');
    if (mode === 'smoke') {
      promptInput.value = defaults.smokePrompt;
      expectedInput.value = defaults.smokeExpectedContent;
      promptInput.disabled = true;
      expectedInput.disabled = true;
      $('tinyWizardProviderNotes').textContent = `${provider.notes || ''} Smoke test uses a fixed prompt and expects ${defaults.smokeExpectedContent}.`.trim();
    } else {
      promptInput.disabled = false;
      expectedInput.disabled = false;
      if (!promptInput.value || promptInput.value === defaults.smokePrompt) promptInput.value = defaults.customPrompt;
      if (!expectedInput.value || expectedInput.value === defaults.smokeExpectedContent) expectedInput.value = defaults.customExpectedContent;
      $('tinyWizardProviderNotes').textContent = `${provider.notes || ''} Custom diagnostic mode checks that the response contains the expected content.`.trim();
    }
  }

  function fillProviderDefaults({ force = false } = {}) {
    const provider = selectedProvider();
    if (!provider) return;
    if (force || !$('tinyWizardLlmBaseUrl').value.trim()) $('tinyWizardLlmBaseUrl').value = provider.default_base_url || '';
    if (force || !$('tinyWizardLlmModel').value.trim() || $('tinyWizardLlmModel').value === 'local-model') $('tinyWizardLlmModel').value = provider.default_model || 'local-model';
    if (force || !$('tinyWizardApiStyle').value.trim()) $('tinyWizardApiStyle').value = provider.api_style || 'openai-compatible';
    syncProbeModeUi();
  }

  function syncTransportDefaults() {
    const transport = $('tinyWizardTransport').value;
    const select = $('tinyWizardPolicyPack');
    const packOptions = tinyState.wizard.policyPacks.filter((item) => (item.transport || 'http') === transport);
    const current = select.value;
    select.innerHTML = '';
    packOptions.forEach((item) => {
      const option = document.createElement('option');
      option.value = item.pack_id;
      option.textContent = `${item.label} · ${(item.description || '').slice(0, 72)}`;
      select.appendChild(option);
    });
    if (packOptions.some((item) => item.pack_id === current)) {
      select.value = current;
    } else if (transport === 'simulated' && packOptions.some((item) => item.pack_id === 'simulated_lab')) {
      select.value = 'simulated_lab';
    } else if (packOptions.some((item) => item.pack_id === 'tiny_openclaw_local')) {
      select.value = 'tiny_openclaw_local';
    } else if (packOptions[0]) {
      select.value = packOptions[0].pack_id;
    }
    if (transport === 'simulated') {
      $('tinyWizardBaseUrl').value = $('tinyWizardBaseUrl').value.trim() || 'simulated://openclaw';
      $('tinyWizardHint').textContent = 'Simulated lab mode is useful for quick validation before connecting a real local runtime endpoint.';
    } else {
      if ($('tinyWizardBaseUrl').value.trim() === 'simulated://openclaw') $('tinyWizardBaseUrl').value = '';
      $('tinyWizardHint').textContent = 'Register a real Tiny runtime endpoint and keep the local LLM profile under openMiura governance.';
    }
    updateWizardPreview();
  }

  function wizardPayload() {
    const provider = selectedProvider() || {};
    const pack = selectedPolicyPack() || {};
    const probeDefaults = currentProbeDefaults();
    const transport = $('tinyWizardTransport').value || 'http';
    const skills = parseCsv($('tinyWizardSkills').value);
    const capabilities = parseCsv($('tinyWizardCapabilities').value);
    const allowedAgents = parseCsv($('tinyWizardAllowedAgents').value);
    const trustedSignerFingerprints = parseCsv($('tinyWizardTrustedSignerFingerprints').value).map((item) => item.toLowerCase());
    const trustedOrganizationIds = parseCsv($('tinyWizardTrustedOrganizationIds').value);
    const trustedOrgRootFingerprints = parseCsv($('tinyWizardTrustedOrgRootFingerprints').value).map((item) => item.toLowerCase());
    const previousSigningKeyIds = parseCsv($('tinyWizardPreviousSigningKeyIds').value);
    const previousSigningFingerprints = parseCsv($('tinyWizardPreviousSigningFingerprints').value).map((item) => item.toLowerCase());
    const baseUrlRaw = $('tinyWizardBaseUrl').value.trim();
    const probeMode = $('tinyWizardChatProbeMode').value || probeDefaults.mode || 'smoke';
    const probePrompt = probeMode === 'smoke'
      ? probeDefaults.smokePrompt
      : ($('tinyWizardChatProbePrompt').value.trim() || probeDefaults.customPrompt);
    const expectedContent = probeMode === 'smoke'
      ? probeDefaults.smokeExpectedContent
      : ($('tinyWizardChatProbeExpectedContent').value.trim() || probeDefaults.customExpectedContent);
    const payload = {
      name: $('tinyWizardName').value.trim() || 'Tiny OpenClaw Local',
      transport,
      base_url: transport === 'simulated' ? (baseUrlRaw || 'simulated://openclaw') : baseUrlRaw,
      template_category: $('tinyWizardTemplateCategory').value || 'general',
      auth_secret_ref: $('tinyWizardAuthSecretRef').value.trim(),
      tenant_id: $('tinyWizardTenantId').value.trim() || undefined,
      workspace_id: $('tinyWizardWorkspaceId').value.trim() || undefined,
      environment: $('tinyWizardEnvironment').value.trim() || undefined,
      capabilities,
      allowed_agents: allowedAgents,
      exchange_signing: {
        sign_package: !!$('tinyWizardSignPackage').checked,
        provider: $('tinyWizardSigningProvider').value || signingDefaults().provider,
        key_id: $('tinyWizardSigningKeyId').value.trim() || signingDefaults().keyId,
        require_signature: !!$('tinyWizardRequireSignature').checked,
        trusted_signer_fingerprints: trustedSignerFingerprints,
        organizational_certificate: {
          include_on_export: !!$('tinyWizardIncludeOrgCertificate').checked,
          require_on_import: !!$('tinyWizardRequireCertificate').checked,
          organization_id: $('tinyWizardOrganizationId').value.trim() || signingDefaults().organizationId,
          organization_name: $('tinyWizardOrganizationName').value.trim() || signingDefaults().organizationName,
          organization_unit: $('tinyWizardOrganizationUnit').value.trim() || signingDefaults().organizationUnit,
          certificate_role: $('tinyWizardCertificateRole').value.trim() || signingDefaults().certificateRole,
          root_key_id: $('tinyWizardRootKeyId').value.trim() || signingDefaults().rootKeyId,
          certificate_key_epoch: Number($('tinyWizardCertificateKeyEpoch').value || signingDefaults().certificateKeyEpoch || 1),
          previous_signing_key_ids: previousSigningKeyIds,
          previous_signing_fingerprints: previousSigningFingerprints,
          trusted_organization_ids: trustedOrganizationIds,
          trusted_org_root_fingerprints: trustedOrgRootFingerprints,
          allow_rotated_signers: !!$('tinyWizardAllowRotatedSigners').checked,
        },
      },
      trust_store: trustStorePayload(),
      metadata: {
        kind: 'tiny_openclaw',
        policy_pack: $('tinyWizardPolicyPack').value || 'tiny_openclaw_local',
        runtime_class: pack.runtime_class || $('tinyWizardPolicyPack').value || 'tiny_openclaw_local',
        skills,
        local_llm: {
          mode: 'local',
          provider: provider.provider_id || 'ollama',
          model: $('tinyWizardLlmModel').value.trim() || provider.default_model || 'local-model',
          base_url: $('tinyWizardLlmBaseUrl').value.trim() || provider.default_base_url || '',
          api_style: $('tinyWizardApiStyle').value.trim() || provider.api_style || 'openai-compatible',
          notes: provider.notes || '',
          chat_completion_probe: {
            enabled: !!$('tinyWizardChatProbeEnabled').checked,
            mode: probeMode,
            smoke_prompt: probeDefaults.smokePrompt,
            smoke_expected_content: probeDefaults.smokeExpectedContent,
            prompt: probePrompt,
            expected_content: expectedContent,
            max_tokens: probeMode === 'smoke' ? 12 : probeDefaults.maxTokens,
            temperature: probeDefaults.temperature,
          },
        },
        session_bridge: {
          enabled: !!$('tinyWizardSessionBridge').checked,
          event_bridge_enabled: !!$('tinyWizardEventBridge').checked,
        },
        state_bridge: {
          enabled: !!$('tinyWizardStateBridge').checked,
          storage: $('tinyWizardStateStorage').value.trim() || 'sqlite',
        },
      },
    };
    if (!payload.auth_secret_ref) delete payload.auth_secret_ref;
    if (!payload.tenant_id) delete payload.tenant_id;
    if (!payload.workspace_id) delete payload.workspace_id;
    if (!payload.environment) delete payload.environment;
    return payload;
  }


  function renderWizardTemplateCategories() {
    const select = $('tinyWizardTemplateCategory');
    const categories = tinyState.wizard.templateCategories || [];
    select.innerHTML = '';
    (categories.length ? categories : [{ category_id: 'general', label: 'General local profile' }]).forEach((item) => {
      const option = document.createElement('option');
      option.value = item.category_id || 'general';
      option.textContent = item.label || item.category_id || 'general';
      select.appendChild(option);
    });
    if (!select.value) select.value = 'general';
  }

  function renderWizardTemplateLibrary() {
    const library = $('tinyWizardTemplateLibrary');
    const summary = tinyState.wizard.summary || {};
    const counts = summary.category_counts || {};
    const pieces = Object.entries(counts).map(([key, value]) => `${key}: ${value}`);
    library.textContent = pieces.length ? `Library by category · ${pieces.join(' · ')}` : 'Library by category · empty';
  }

  function renderWizardTemplates() {
    const select = $('tinyWizardTemplateSelect');
    const templates = tinyState.wizard.templates || [];
    select.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = templates.length ? 'Choose a saved template…' : 'No saved templates yet';
    select.appendChild(placeholder);
    templates.forEach((item) => {
      const option = document.createElement('option');
      option.value = item.template_id || '';
      const summary = item.summary || {};
      option.textContent = `${item.template_name || 'template'} · ${summary.template_category || 'general'} · ${summary.llm_provider || 'local'} · ${summary.policy_pack || 'policy'}`;
      select.appendChild(option);
    });
  }

  function populateImportApprovalOptions() {
    const select = $('tinyWizardImportApprovalSelect');
    const approvals = tinyState.wizard.importApprovals || [];
    select.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = approvals.length ? 'Choose a pending import approval…' : 'No pending import approvals';
    select.appendChild(placeholder);
    approvals.forEach((item) => {
      const option = document.createElement('option');
      option.value = item.approval_id || '';
      option.textContent = `${item.status || 'pending'} · ${(item.summary || {}).template_name || item.workflow_id || item.approval_id || 'approval'}`;
      select.appendChild(option);
    });
    const current = approvals.find((item) => item.approval_id === select.value) || approvals[0] || null;
    $('tinyWizardImportApprovalBox').textContent = pretty(current || {});
  }

  function populateTrustDecisionOptions() {
    const select = $('tinyWizardTrustDecisionSelect');
    const decisions = tinyState.wizard.trustDecisions || [];
    select.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = decisions.length ? 'Choose a trust decision…' : 'No trust decisions yet';
    select.appendChild(placeholder);
    decisions.forEach((item) => {
      const option = document.createElement('option');
      option.value = item.decision_id || '';
      option.textContent = `${item.status || 'observed'} · ${item.decision_kind || 'trust'} · ${item.latest_event || 'event'}`;
      select.appendChild(option);
    });
    const current = decisions.find((item) => item.decision_id === select.value) || decisions[0] || null;
    $('tinyWizardTrustDecisionBox').textContent = pretty(current || {});
  }

  async function refreshWizardCertificateProfiles({ silent = false } = {}) {
    try {
      const params = new URLSearchParams();
      const tenantId = $('tinyWizardTenantId').value.trim();
      const workspaceId = $('tinyWizardWorkspaceId').value.trim();
      const environment = $('tinyWizardEnvironment').value.trim();
      if (tenantId) params.set('tenant_id', tenantId);
      if (workspaceId) params.set('workspace_id', workspaceId);
      if (environment) params.set('environment', environment);
      const payload = await api(`/admin/openclaw/tiny-runtime-wizard/certificates${params.toString() ? `?${params.toString()}` : ''}`);
      tinyState.wizard.certificateProfiles = payload.items || [];
      tinyState.wizard.certificateProfilesSummary = payload.summary || {};
      populateCertificateProfileOptions();
      if (!silent) setStatus(`Loaded ${tinyState.wizard.certificateProfiles.length} certificate profile${tinyState.wizard.certificateProfiles.length === 1 ? '' : 's'}.`, 'ok');
      return payload;
    } catch (error) {
      if (!silent) setStatus(error.message, 'danger');
      throw error;
    }
  }

  function certificateLifecyclePayload() {
    return {
      profile_name: $('tinyWizardCertificateProfileName').value.trim() || $('tinyWizardOrganizationName').value.trim() || 'Tiny runtime signer',
      organization_id: $('tinyWizardOrganizationId').value.trim() || signingDefaults().organizationId,
      organization_name: $('tinyWizardOrganizationName').value.trim() || signingDefaults().organizationName,
      organization_unit: $('tinyWizardOrganizationUnit').value.trim() || signingDefaults().organizationUnit,
      certificate_role: $('tinyWizardCertificateRole').value.trim() || signingDefaults().certificateRole,
      root_key_id: $('tinyWizardRootKeyId').value.trim() || signingDefaults().rootKeyId,
      signing_provider: $('tinyWizardSigningProvider').value || signingDefaults().provider,
      signing_key_id: $('tinyWizardSigningKeyId').value.trim() || signingDefaults().keyId,
      certificate_key_epoch: Number($('tinyWizardCertificateKeyEpoch').value || signingDefaults().certificateKeyEpoch || 1),
      certificate_validity_days: Number($('tinyWizardCertificateValidityDays').value || certificateLifecycleDefaults().certificateValidityDays || 365),
      tenant_id: $('tinyWizardTenantId').value.trim() || undefined,
      workspace_id: $('tinyWizardWorkspaceId').value.trim() || undefined,
      environment: $('tinyWizardEnvironment').value.trim() || undefined,
      sync_trust_store: !!$('tinyWizardSyncTrustStoreOnCertificateLifecycle').checked,
      scope_level: $('tinyWizardTrustStoreLevel').value || certificateLifecycleDefaults().defaultScopeLevel || 'environment',
    };
  }

  async function issueWizardCertificateProfile() {
    try {
      if (!tinyState.wizard.loaded) await loadWizardDefaults({ silent: true });
      const response = await api('/admin/openclaw/tiny-runtime-wizard/certificates/issue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(certificateLifecyclePayload()),
      });
      $('tinyWizardResultBox').textContent = pretty(response);
      await refreshWizardCertificateProfiles({ silent: true });
      await refreshWizardTrustDecisions({ silent: true });
      if (response.profile) {
        $('tinyWizardCertificateProfileSelect').value = response.profile.profile_id || '';
        applyCertificateProfileToWizard(response.profile);
      }
      if (response.trust_store && response.trust_store.ok) await refreshWizardTrustStore({ silent: true });
      setStatus('Certificate profile issued.', 'ok');
      return response;
    } catch (error) {
      setStatus(error.message, 'danger');
      $('tinyWizardResultBox').textContent = pretty({ ok: false, error: error.message });
      return null;
    }
  }

  async function rotateWizardCertificateProfile() {
    try {
      const profile = selectedCertificateProfile();
      if (!profile) {
        setStatus('Choose a certificate profile first.', 'danger');
        return null;
      }
      const payload = certificateLifecyclePayload();
      const response = await api(`/admin/openclaw/tiny-runtime-wizard/certificates/${encodeURIComponent(profile.profile_id)}/rotate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      $('tinyWizardResultBox').textContent = pretty(response);
      await refreshWizardCertificateProfiles({ silent: true });
      await refreshWizardTrustDecisions({ silent: true });
      if (response.profile) {
        $('tinyWizardCertificateProfileSelect').value = response.profile.profile_id || '';
        applyCertificateProfileToWizard(response.profile);
      }
      if (response.trust_store && response.trust_store.ok) await refreshWizardTrustStore({ silent: true });
      setStatus('Certificate profile rotated.', 'ok');
      return response;
    } catch (error) {
      setStatus(error.message, 'danger');
      $('tinyWizardResultBox').textContent = pretty({ ok: false, error: error.message });
      return null;
    }
  }

  async function revokeWizardCertificateProfile() {
    try {
      const profile = selectedCertificateProfile();
      if (!profile) {
        setStatus('Choose a certificate profile first.', 'danger');
        return null;
      }
      const payload = {
        ...certificateLifecyclePayload(),
        reason: `Revoked from Tiny runtime wizard`,
      };
      const response = await api(`/admin/openclaw/tiny-runtime-wizard/certificates/${encodeURIComponent(profile.profile_id)}/revoke`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      $('tinyWizardResultBox').textContent = pretty(response);
      await refreshWizardCertificateProfiles({ silent: true });
      await refreshWizardTrustDecisions({ silent: true });
      if (response.profile) {
        $('tinyWizardCertificateProfileSelect').value = response.profile.profile_id || '';
        $('tinyWizardCertificateProfileBox').textContent = pretty(response.profile);
      }
      if (response.trust_store && response.trust_store.ok) await refreshWizardTrustStore({ silent: true });
      setStatus('Certificate profile revoked.', 'ok');
      return response;
    } catch (error) {
      setStatus(error.message, 'danger');
      $('tinyWizardResultBox').textContent = pretty({ ok: false, error: error.message });
      return null;
    }
  }

  async function refreshWizardImportApprovals({ silent = false } = {}) {
    try {
      const params = new URLSearchParams();
      const tenantId = $('tinyWizardTenantId').value.trim();
      const workspaceId = $('tinyWizardWorkspaceId').value.trim();
      const environment = $('tinyWizardEnvironment').value.trim();
      if (tenantId) params.set('tenant_id', tenantId);
      if (workspaceId) params.set('workspace_id', workspaceId);
      if (environment) params.set('environment', environment);
      params.set('status', 'pending');
      const payload = await api(`/admin/openclaw/tiny-runtime-wizard/templates/import-approvals${params.toString() ? `?${params.toString()}` : ''}`);
      tinyState.wizard.importApprovals = payload.items || [];
      tinyState.wizard.importApprovalsSummary = payload.summary || {};
      populateImportApprovalOptions();
      if (!silent) setStatus(`Loaded ${tinyState.wizard.importApprovals.length} pending import approval${tinyState.wizard.importApprovals.length === 1 ? '' : 's'}.`, 'ok');
      return payload;
    } catch (error) {
      if (!silent) setStatus(error.message, 'danger');
      throw error;
    }
  }

  async function refreshWizardTrustDecisions({ silent = false } = {}) {
    try {
      const params = new URLSearchParams();
      const tenantId = $('tinyWizardTenantId').value.trim();
      const workspaceId = $('tinyWizardWorkspaceId').value.trim();
      const environment = $('tinyWizardEnvironment').value.trim();
      if (tenantId) params.set('tenant_id', tenantId);
      if (workspaceId) params.set('workspace_id', workspaceId);
      if (environment) params.set('environment', environment);
      const payload = await api(`/admin/openclaw/tiny-runtime-wizard/trust-decisions${params.toString() ? `?${params.toString()}` : ''}`);
      tinyState.wizard.trustDecisions = payload.items || [];
      tinyState.wizard.trustDecisionsSummary = payload.summary || {};
      populateTrustDecisionOptions();
      if (!silent) setStatus(`Loaded ${tinyState.wizard.trustDecisions.length} trust decision${tinyState.wizard.trustDecisions.length === 1 ? '' : 's'}.`, 'ok');
      return payload;
    } catch (error) {
      if (!silent) setStatus(error.message, 'danger');
      throw error;
    }
  }

  async function replayTrustDecision() {
    try {
      const decisionId = $('tinyWizardTrustDecisionSelect').value;
      if (!decisionId) {
        setStatus('Choose a trust decision first.', 'danger');
        return;
      }
      const params = new URLSearchParams();
      const tenantId = $('tinyWizardTenantId').value.trim();
      const workspaceId = $('tinyWizardWorkspaceId').value.trim();
      const environment = $('tinyWizardEnvironment').value.trim();
      if (tenantId) params.set('tenant_id', tenantId);
      if (workspaceId) params.set('workspace_id', workspaceId);
      if (environment) params.set('environment', environment);
      const payload = await api(`/admin/openclaw/tiny-runtime-wizard/trust-decisions/${encodeURIComponent(decisionId)}/replay${params.toString() ? `?${params.toString()}` : ''}`);
      $('tinyWizardResultBox').textContent = pretty(payload);
      $('tinyWizardTrustDecisionBox').textContent = pretty(payload);
      setStatus(`Replayed trust decision ${decisionId}.`, 'ok');
      return payload;
    } catch (error) {
      setStatus(error.message, 'danger');
      $('tinyWizardResultBox').textContent = pretty({ ok: false, error: error.message });
      throw error;
    }
  }

  async function refreshWizardTrustStore({ silent = false } = {}) {
    try {
      const params = new URLSearchParams();
      const tenantId = $('tinyWizardTenantId').value.trim();
      const workspaceId = $('tinyWizardWorkspaceId').value.trim();
      const environment = $('tinyWizardEnvironment').value.trim();
      const scopeLevel = $('tinyWizardTrustStoreLevel').value || 'environment';
      if (tenantId) params.set('tenant_id', tenantId);
      if (workspaceId) params.set('workspace_id', workspaceId);
      if (environment) params.set('environment', environment);
      if (scopeLevel) params.set('scope_level', scopeLevel);
      const payload = await api(`/admin/openclaw/tiny-runtime-wizard/trust-store${params.toString() ? `?${params.toString()}` : ''}`);
      tinyState.wizard.selectedTrustStoreLevel = scopeLevel;
      tinyState.wizard.trustStore = payload.trust_store || {};
      tinyState.wizard.trustStoreSummary = payload.summary || {};
      tinyState.wizard.effectiveTrustStore = payload.effective_trust_store || payload.trust_store || {};
      tinyState.wizard.effectiveTrustStoreSummary = payload.effective_summary || payload.summary || {};
      tinyState.wizard.trustStoreHierarchy = payload.hierarchy || [];
      const trustStore = tinyState.wizard.trustStore || {};
      const denylist = trustStore.denylist || {};
      const crl = trustStore.crl || {};
      $('tinyWizardRequireSignature').checked = trustStore.require_signature !== false;
      $('tinyWizardRequireCertificate').checked = trustStore.require_certificate !== false;
      $('tinyWizardAllowRotatedSigners').checked = trustStore.allow_rotated_signers !== false;
      $('tinyWizardTrustedSignerFingerprints').value = (trustStore.trusted_signer_fingerprints || []).join(', ');
      $('tinyWizardTrustedOrganizationIds').value = (trustStore.trusted_organization_ids || []).join(', ');
      $('tinyWizardTrustedOrgRootFingerprints').value = (trustStore.trusted_org_root_fingerprints || []).join(', ');
      $('tinyWizardDeniedPackageHashes').value = (denylist.package_sha256 || []).join(', ');
      $('tinyWizardRevokedSignerFingerprints').value = (denylist.signer_fingerprints || []).join(', ');
      $('tinyWizardRevokedSigningKeyIds').value = (denylist.signing_key_ids || []).join(', ');
      $('tinyWizardRevokedOrganizationIds').value = (denylist.organization_ids || []).join(', ');
      $('tinyWizardRevokedOrgRootFingerprints').value = (denylist.org_root_fingerprints || []).join(', ');
      $('tinyWizardRevokedCertificateFingerprints').value = (denylist.certificate_fingerprints || []).join(', ');
      $('tinyWizardRevokedCertificateIds').value = (denylist.certificate_ids || []).join(', ');
      $('tinyWizardCertificateRevocationList').value = pretty(crl.revoked_certificates || []);
      renderTrustStoreSummary();
      updateWizardPreview();
      if (!silent) setStatus(`Loaded ${scopeLevel} trust store.`, 'ok');
      return payload;
    } catch (error) {
      if (!silent) setStatus(error.message, 'danger');
      throw error;
    }
  }

  async function decideWizardImportApproval(action) {
    try {
      const approvalId = $('tinyWizardImportApprovalSelect').value;
      if (!approvalId) {
        setStatus('Choose an import approval first.', 'danger');
        return;
      }
      const response = await api(`/admin/openclaw/tiny-runtime-wizard/templates/import-approvals/${encodeURIComponent(approvalId)}/actions/${encodeURIComponent(action)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tenant_id: $('tinyWizardTenantId').value.trim() || undefined,
          workspace_id: $('tinyWizardWorkspaceId').value.trim() || undefined,
          environment: $('tinyWizardEnvironment').value.trim() || undefined,
          scope_level: $('tinyWizardTrustStoreLevel').value || 'environment',
        }),
      });
      $('tinyWizardResultBox').textContent = pretty(response);
      await refreshWizardImportApprovals({ silent: true });
      await refreshWizardTrustDecisions({ silent: true });
      await refreshWizardCertificateProfiles({ silent: true });
      await loadWizardDefaults({ silent: true });
      const approved = action === 'approve' && response.import_result && response.import_result.ok;
      setStatus(approved ? 'Template import approved and executed.' : `Import approval ${action}d.`, approved ? 'ok' : 'muted');
    } catch (error) {
      setStatus(error.message, 'danger');
      $('tinyWizardResultBox').textContent = pretty({ ok: false, error: error.message });
    }
  }

  function applyTemplateToWizard(entry) {
    if (!entry) return;
    const payload = entry.template || {};
    const metadata = payload.metadata || {};
    const localLlm = metadata.local_llm || {};
    const probe = localLlm.chat_completion_probe || {};
    $('tinyWizardTemplateName').value = entry.template_name || '';
    $('tinyWizardTemplateCategory').value = entry.template_category || (entry.summary || {}).template_category || payload.template_category || 'general';
    $('tinyWizardName').value = payload.name || 'Tiny OpenClaw Local';
    $('tinyWizardTransport').value = payload.transport || 'http';
    $('tinyWizardBaseUrl').value = payload.base_url || '';
    $('tinyWizardAuthSecretRef').value = payload.auth_secret_ref || '';
    $('tinyWizardTenantId').value = payload.tenant_id || '';
    $('tinyWizardWorkspaceId').value = payload.workspace_id || '';
    $('tinyWizardEnvironment').value = payload.environment || '';
    $('tinyWizardAllowedAgents').value = (payload.allowed_agents || []).join(', ');
    $('tinyWizardSkills').value = (metadata.skills || []).join(', ');
    $('tinyWizardCapabilities').value = (payload.capabilities || []).join(', ');
    $('tinyWizardLlmProvider').value = localLlm.provider || $('tinyWizardLlmProvider').value || 'ollama';
    syncTransportDefaults();
    $('tinyWizardPolicyPack').value = metadata.policy_pack || $('tinyWizardPolicyPack').value || 'tiny_openclaw_local';
    $('tinyWizardLlmModel').value = localLlm.model || '';
    $('tinyWizardLlmBaseUrl').value = localLlm.base_url || '';
    $('tinyWizardApiStyle').value = localLlm.api_style || 'openai-compatible';
    $('tinyWizardStateStorage').value = ((metadata.state_bridge || {}).storage) || 'sqlite';
    $('tinyWizardSessionBridge').checked = !!((metadata.session_bridge || {}).enabled);
    $('tinyWizardEventBridge').checked = !!((metadata.session_bridge || {}).event_bridge_enabled);
    $('tinyWizardStateBridge').checked = !!((metadata.state_bridge || {}).enabled);
    $('tinyWizardChatProbeEnabled').checked = !!probe.enabled;
    $('tinyWizardChatProbeMode').value = probe.mode || 'smoke';
    $('tinyWizardChatProbePrompt').value = probe.prompt || probe.smoke_prompt || '';
    $('tinyWizardChatProbeExpectedContent').value = probe.expected_content || probe.smoke_expected_content || '';
    syncProbeModeUi();
    updateWizardPreview();
    setStatus(`Loaded template ${entry.template_name || ''}`.trim(), 'ok');
  }

  async function saveWizardTemplate() {
    try {
      if (!tinyState.wizard.loaded) await loadWizardDefaults({ silent: true });
      const templateName = $('tinyWizardTemplateName').value.trim();
      if (!templateName) {
        setStatus('Template name is required.', 'danger');
        return;
      }
      const payload = updateWizardPreview();
      const response = await api('/admin/openclaw/tiny-runtime-wizard/templates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ template_name: templateName, ...payload }),
      });
      $('tinyWizardResultBox').textContent = pretty(response);
      await loadWizardDefaults({ silent: true });
      const savedId = response.template?.template_id || '';
      if (savedId) $('tinyWizardTemplateSelect').value = savedId;
      setStatus(`Saved runtime template ${response.template?.template_name || templateName}`.trim(), 'ok');
    } catch (error) {
      setStatus(error.message, 'danger');
      $('tinyWizardResultBox').textContent = pretty({ ok: false, error: error.message });
    }
  }

  async function updateWizardTemplate() {
    try {
      if (!tinyState.wizard.loaded) await loadWizardDefaults({ silent: true });
      const templateId = $('tinyWizardTemplateSelect').value;
      if (!templateId) {
        setStatus('Choose a saved template before updating it.', 'danger');
        return;
      }
      const templateName = $('tinyWizardTemplateName').value.trim();
      if (!templateName) {
        setStatus('Template name is required.', 'danger');
        return;
      }
      const payload = updateWizardPreview();
      const response = await api(`/admin/openclaw/tiny-runtime-wizard/templates/${encodeURIComponent(templateId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ template_name: templateName, ...payload }),
      });
      $('tinyWizardResultBox').textContent = pretty(response);
      await loadWizardDefaults({ silent: true });
      $('tinyWizardTemplateSelect').value = response.template?.template_id || templateId;
      setStatus(`Updated runtime template ${response.template?.template_name || templateName}`.trim(), 'ok');
    } catch (error) {
      setStatus(error.message, 'danger');
      $('tinyWizardResultBox').textContent = pretty({ ok: false, error: error.message });
    }
  }

  async function cloneWizardTemplate() {
    try {
      if (!tinyState.wizard.loaded) await loadWizardDefaults({ silent: true });
      const templateId = $('tinyWizardTemplateSelect').value;
      if (!templateId) {
        setStatus('Choose a saved template before cloning it.', 'danger');
        return;
      }
      const requestedName = $('tinyWizardTemplateName').value.trim();
      const response = await api(`/admin/openclaw/tiny-runtime-wizard/templates/${encodeURIComponent(templateId)}/clone`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          template_name: requestedName,
          template_category: $('tinyWizardTemplateCategory').value || undefined,
          tenant_id: $('tinyWizardTenantId').value.trim() || undefined,
          workspace_id: $('tinyWizardWorkspaceId').value.trim() || undefined,
          environment: $('tinyWizardEnvironment').value.trim() || undefined,
          scope_level: $('tinyWizardTrustStoreLevel').value || 'environment',
        }),
      });
      $('tinyWizardResultBox').textContent = pretty(response);
      await loadWizardDefaults({ silent: true });
      const clonedId = response.template?.template_id || '';
      if (clonedId) $('tinyWizardTemplateSelect').value = clonedId;
      const selected = (tinyState.wizard.templates || []).find((item) => item.template_id === clonedId);
      if (selected) applyTemplateToWizard(selected);
      setStatus(`Cloned runtime template ${response.template?.template_name || requestedName || 'template copy'}`.trim(), 'ok');
    } catch (error) {
      setStatus(error.message, 'danger');
      $('tinyWizardResultBox').textContent = pretty({ ok: false, error: error.message });
    }
  }

  async function exportWizardTemplates() {
    try {
      if (!tinyState.wizard.loaded) await loadWizardDefaults({ silent: true });
      const params = new URLSearchParams();
      const templateId = $('tinyWizardTemplateSelect').value;
      const tenantId = $('tinyWizardTenantId').value.trim();
      const workspaceId = $('tinyWizardWorkspaceId').value.trim();
      const environment = $('tinyWizardEnvironment').value.trim();
      if (templateId) params.set('template_ids', templateId);
      if (tenantId) params.set('tenant_id', tenantId);
      if (workspaceId) params.set('workspace_id', workspaceId);
      if (environment) params.set('environment', environment);
      params.set('sign_package', $('tinyWizardSignPackage').checked ? 'true' : 'false');
      const signingProvider = $('tinyWizardSigningProvider').value || signingDefaults().provider;
      const signingKeyId = $('tinyWizardSigningKeyId').value.trim() || signingDefaults().keyId;
      if (signingProvider) params.set('signing_provider', signingProvider);
      if (signingKeyId) params.set('signing_key_id', signingKeyId);
      params.set('include_organizational_certificate', $('tinyWizardIncludeOrgCertificate').checked ? 'true' : 'false');
      const organizationId = $('tinyWizardOrganizationId').value.trim();
      const organizationName = $('tinyWizardOrganizationName').value.trim();
      const organizationUnit = $('tinyWizardOrganizationUnit').value.trim();
      const certificateRole = $('tinyWizardCertificateRole').value.trim();
      const rootKeyId = $('tinyWizardRootKeyId').value.trim();
      const certificateKeyEpoch = $('tinyWizardCertificateKeyEpoch').value.trim();
      const previousSigningKeyIds = $('tinyWizardPreviousSigningKeyIds').value.trim();
      const previousSigningFingerprints = $('tinyWizardPreviousSigningFingerprints').value.trim();
      if (organizationId) params.set('organization_id', organizationId);
      if (organizationName) params.set('organization_name', organizationName);
      if (organizationUnit) params.set('organization_unit', organizationUnit);
      if (certificateRole) params.set('certificate_role', certificateRole);
      if (rootKeyId) params.set('root_key_id', rootKeyId);
      if (certificateKeyEpoch) params.set('certificate_key_epoch', certificateKeyEpoch);
      if (previousSigningKeyIds) params.set('previous_signing_key_ids', previousSigningKeyIds);
      if (previousSigningFingerprints) params.set('previous_signing_fingerprints', previousSigningFingerprints);
      const response = await api(`/admin/openclaw/tiny-runtime-wizard/templates/export${params.toString() ? `?${params.toString()}` : ''}`);
      $('tinyWizardTemplateExchange').value = pretty(response.export || {});
      $('tinyWizardResultBox').textContent = pretty(response);
      const count = response.summary?.count || 0;
      const sha256 = (response.integrity && response.integrity.sha256) || (response.export && response.export.integrity && response.export.integrity.sha256) || '';
      const signer = (response.signature && (((response.signature.public_key || {}).public_key_fingerprint) || response.signature.signer_provider)) || '';
      const orgId = (response.summary && response.summary.organization_id) || '';
      const orgRoot = (response.summary && response.summary.organization_root_fingerprint) || '';
      const digestHint = sha256 ? ` SHA256 ${sha256.slice(0, 12)}…` : '';
      const signerHint = signer ? ` Signature ${String(signer).slice(0, 12)}…` : '';
      const certHint = orgId ? ` Org cert ${String(orgId)}${orgRoot ? `/${String(orgRoot).slice(0, 12)}…` : ''}.` : '';
      setStatus(count ? `Exported ${count} runtime template${count === 1 ? '' : 's'} to JSON.${digestHint}${signerHint}${certHint}` : 'No templates available to export in this scope.', count ? 'ok' : 'danger');
    } catch (error) {
      setStatus(error.message, 'danger');
      $('tinyWizardResultBox').textContent = pretty({ ok: false, error: error.message });
    }
  }


  async function importWizardTemplates() {
    try {
      if (!tinyState.wizard.loaded) await loadWizardDefaults({ silent: true });
      const raw = $('tinyWizardTemplateExchange').value.trim();
      if (!raw) {
        setStatus('Paste exported template JSON before importing it.', 'danger');
        return;
      }
      const parsed = JSON.parse(raw);
      const response = await api('/admin/openclaw/tiny-runtime-wizard/templates/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          export: parsed,
          overwrite_existing: !!$('tinyWizardImportOverwrite').checked,
          preserve_source_scope: !!$('tinyWizardImportPreserveScope').checked,
          require_signature: !!$('tinyWizardRequireSignature').checked,
          trusted_signer_fingerprints: parseCsv($('tinyWizardTrustedSignerFingerprints').value).map((item) => item.toLowerCase()),
          require_certificate: !!$('tinyWizardRequireCertificate').checked,
          trusted_org_root_fingerprints: parseCsv($('tinyWizardTrustedOrgRootFingerprints').value).map((item) => item.toLowerCase()),
          trusted_organization_ids: parseCsv($('tinyWizardTrustedOrganizationIds').value),
          revoked_signer_fingerprints: parseCsv($('tinyWizardRevokedSignerFingerprints').value).map((item) => item.toLowerCase()),
          revoked_signing_key_ids: parseCsv($('tinyWizardRevokedSigningKeyIds').value),
          revoked_org_root_fingerprints: parseCsv($('tinyWizardRevokedOrgRootFingerprints').value).map((item) => item.toLowerCase()),
          revoked_organization_ids: parseCsv($('tinyWizardRevokedOrganizationIds').value),
          revoked_certificate_fingerprints: parseCsv($('tinyWizardRevokedCertificateFingerprints').value).map((item) => item.toLowerCase()),
          revoked_certificate_ids: parseCsv($('tinyWizardRevokedCertificateIds').value),
          denied_package_hashes: parseCsv($('tinyWizardDeniedPackageHashes').value).map((item) => item.toLowerCase()),
          allow_rotated_signers: !!$('tinyWizardAllowRotatedSigners').checked,
          tenant_id: $('tinyWizardTenantId').value.trim() || undefined,
          workspace_id: $('tinyWizardWorkspaceId').value.trim() || undefined,
          environment: $('tinyWizardEnvironment').value.trim() || undefined,
          scope_level: $('tinyWizardTrustStoreLevel').value || 'environment',
        }),
      });
      $('tinyWizardResultBox').textContent = pretty(response);
      if (response.approval_required) {
        if (response.approval) {
          tinyState.wizard.importApprovals = [response.approval, ...(tinyState.wizard.importApprovals || []).filter((item) => item.approval_id !== response.approval.approval_id)];
          populateImportApprovalOptions();
          $('tinyWizardImportApprovalSelect').value = response.approval.approval_id || '';
          $('tinyWizardImportApprovalBox').textContent = pretty(response.approval);
        }
        setStatus('Signed template import requires approval before execution.', 'muted');
        return;
      }
      await loadWizardDefaults({ silent: true });
      await refreshWizardImportApprovals({ silent: true });
      const imported = (response.created || [])[0] || (response.updated || [])[0];
      if (imported?.template_id) $('tinyWizardTemplateSelect').value = imported.template_id;
      const selected = (tinyState.wizard.templates || []).find((item) => item.template_id === $('tinyWizardTemplateSelect').value);
      if (selected) applyTemplateToWizard(selected);
      const summary = response.summary || {};
      const verification = response.verification || {};
      const integrityHint = verification.integrity?.status === 'passed'
        ? ` Integrity verified (${String(verification.expected_hash || verification.provided_hash || '').slice(0, 12)}…).`
        : verification.status && verification.status !== 'not_applicable'
          ? ` Integrity check ${verification.status}.`
          : '';
      const signatureHint = verification.signature?.status === 'passed'
        ? ` Signature verified (${String(verification.signer_fingerprint || '').slice(0, 12)}…).`
        : verification.signature?.status && !['not_applicable', 'not_present'].includes(verification.signature.status)
          ? ` Signature check ${verification.signature.status}.`
          : '';
      const certificateHint = verification.certificate?.status === 'passed'
        ? ` Org certificate verified (${String(verification.certificate.organization_id || '').trim() || 'org'}).`
        : verification.certificate?.status && !['not_applicable', 'not_present'].includes(verification.certificate.status)
          ? ` Org certificate check ${verification.certificate.status}.`
          : '';
      setStatus(`Imported runtime templates · created ${summary.created_count || 0}, updated ${summary.updated_count || 0}, skipped ${summary.skipped_count || 0}.${integrityHint}${signatureHint}${certificateHint}`, response.ok ? 'ok' : 'danger');
    } catch (error) {
      setStatus(error.message, 'danger');
      $('tinyWizardResultBox').textContent = pretty({ ok: false, error: error.message });
    }
  }


  async function saveWizardTrustStore() {
    try {
      if (!tinyState.wizard.loaded) await loadWizardDefaults({ silent: true });
      const response = await api('/admin/openclaw/tiny-runtime-wizard/trust-store', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trust_store: trustStorePayload(),
          tenant_id: $('tinyWizardTenantId').value.trim() || undefined,
          workspace_id: $('tinyWizardWorkspaceId').value.trim() || undefined,
          environment: $('tinyWizardEnvironment').value.trim() || undefined,
          scope_level: $('tinyWizardTrustStoreLevel').value || 'environment',
        }),
      });
      $('tinyWizardResultBox').textContent = pretty(response);
      await loadWizardDefaults({ silent: true });
      setStatus('Saved Tiny runtime template trust policy.', response.ok ? 'ok' : 'danger');
    } catch (error) {
      setStatus(error.message, 'danger');
      $('tinyWizardResultBox').textContent = pretty({ ok: false, error: error.message });
    }
  }


  async function deleteWizardTemplate() {
    try {
      if (!tinyState.wizard.loaded) await loadWizardDefaults({ silent: true });
      const templateId = $('tinyWizardTemplateSelect').value;
      if (!templateId) {
        setStatus('Choose a saved template before deleting it.', 'danger');
        return;
      }
      const selected = (tinyState.wizard.templates || []).find((item) => item.template_id === templateId);
      const templateName = (selected && selected.template_name) || $('tinyWizardTemplateName').value.trim() || 'template';
      const response = await api(`/admin/openclaw/tiny-runtime-wizard/templates/${encodeURIComponent(templateId)}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: `Deleted from Tiny runtime wizard by operator`, tenant_id: $('tinyWizardTenantId').value.trim() || undefined, workspace_id: $('tinyWizardWorkspaceId').value.trim() || undefined, environment: $('tinyWizardEnvironment').value.trim() || undefined }),
      });
      $('tinyWizardResultBox').textContent = pretty(response);
      $('tinyWizardTemplateSelect').value = '';
      await loadWizardDefaults({ silent: true });
      setStatus(`Deleted runtime template ${templateName}`.trim(), 'ok');
    } catch (error) {
      setStatus(error.message, 'danger');
      $('tinyWizardResultBox').textContent = pretty({ ok: false, error: error.message });
    }
  }

  function updateWizardPreview() {
    const payload = wizardPayload();
    $('tinyWizardPreviewBox').textContent = pretty(payload);
    return payload;
  }

  function populateWizard(payload) {
    const wizard = payload.wizard || {};
    tinyState.wizard.loaded = true;
    tinyState.wizard.policyPacks = payload.policy_packs || [];
    tinyState.wizard.providers = payload.llm_providers || [];
    tinyState.wizard.signingProviders = payload.template_signing_providers || [];
    tinyState.wizard.defaults = wizard;
    tinyState.wizard.templates = payload.templates || [];
    tinyState.wizard.templateCategories = payload.template_categories || wizard.template_categories || [];
    tinyState.wizard.summary = payload.template_summary || {};
    tinyState.wizard.trustStore = payload.template_trust_store || wizard.template_exchange_trust_store || {};
    tinyState.wizard.trustStoreSummary = payload.template_trust_store_summary || {};
    tinyState.wizard.effectiveTrustStore = payload.template_trust_store_effective || wizard.template_exchange_trust_store_effective || tinyState.wizard.trustStore || {};
    tinyState.wizard.effectiveTrustStoreSummary = payload.template_trust_store_effective_summary || payload.template_trust_store_summary || {};
    tinyState.wizard.trustStoreHierarchy = payload.template_trust_store_hierarchy || [];
    tinyState.wizard.importApprovals = payload.template_import_approvals || [];
    tinyState.wizard.importApprovalsSummary = payload.template_import_approvals_summary || {};
    tinyState.wizard.trustDecisions = payload.template_trust_decisions || [];
    tinyState.wizard.trustDecisionsSummary = payload.template_trust_decisions_summary || {};
    tinyState.wizard.certificateProfiles = payload.certificate_profiles || [];
    tinyState.wizard.certificateProfilesSummary = payload.certificate_profiles_summary || {};
    tinyState.wizard.trustStoreLevels = payload.template_trust_store_levels || ['environment', 'workspace', 'tenant', 'global'];

    $('tinyWizardTemplateName').value = $('tinyWizardTemplateName').value || '';
    $('tinyWizardCertificateProfileName').value = $('tinyWizardCertificateProfileName').value || '';
    $('tinyWizardName').value = $('tinyWizardName').value || 'Tiny OpenClaw Local';
    $('tinyWizardTransport').value = wizard.recommended_transport || 'http';
    $('tinyWizardEnvironment').value = $('tinyWizardEnvironment').value || (wizard.default_scope || {}).environment || 'dev';
    $('tinyWizardSkills').value = $('tinyWizardSkills').value || ((wizard.recommended_skills || []).join(', '));
    $('tinyWizardCapabilities').value = $('tinyWizardCapabilities').value || ((wizard.recommended_capabilities || []).join(', '));
    $('tinyWizardAllowedAgents').value = $('tinyWizardAllowedAgents').value || ((wizard.template || {}).allowed_agents || ['default']).join(', ');
    $('tinyWizardStateStorage').value = $('tinyWizardStateStorage').value || ((((wizard.template || {}).metadata || {}).state_bridge || {}).storage || 'sqlite');
    const defaultProbe = (((wizard.default_validation || {}).chat_completion_probe) || ((((wizard.template || {}).metadata || {}).local_llm || {}).chat_completion_probe) || {});
    const exchangeSigning = wizard.template_exchange_signing || {};
    const exchangeOrg = exchangeSigning.organizational_certificate || {};
    const trustStore = wizard.template_exchange_trust_store || payload.template_trust_store || {};
    const trustDenylist = trustStore.denylist || {};
    const trustCrl = trustStore.crl || {};
    $('tinyWizardChatProbeEnabled').checked = !!defaultProbe.enabled;
    $('tinyWizardChatProbeMode').value = $('tinyWizardChatProbeMode').value || defaultProbe.mode || 'smoke';
    $('tinyWizardChatProbePrompt').value = $('tinyWizardChatProbePrompt').value || defaultProbe.prompt || 'Reply with: local runtime ready';
    $('tinyWizardChatProbeExpectedContent').value = $('tinyWizardChatProbeExpectedContent').value || defaultProbe.expected_content || 'local runtime ready';
    $('tinyWizardSignPackage').checked = exchangeSigning.sign_package !== false;
    $('tinyWizardRequireSignature').checked = exchangeSigning.require_signature_on_import !== false;
    $('tinyWizardIncludeOrgCertificate').checked = exchangeOrg.include_on_export !== false;
    $('tinyWizardRequireCertificate').checked = exchangeOrg.require_on_import !== false;
    $('tinyWizardAllowRotatedSigners').checked = exchangeOrg.allow_rotated_signers !== false;
    $('tinyWizardSigningKeyId').value = $('tinyWizardSigningKeyId').value || exchangeSigning.key_id || 'tiny-runtime-template-package';
    $('tinyWizardOrganizationId').value = $('tinyWizardOrganizationId').value || exchangeOrg.organization_id || 'openmiura-local';
    $('tinyWizardOrganizationName').value = $('tinyWizardOrganizationName').value || exchangeOrg.organization_name || 'OpenMiura Local Trust';
    $('tinyWizardOrganizationUnit').value = $('tinyWizardOrganizationUnit').value || exchangeOrg.organization_unit || 'Tiny Runtime Templates';
    $('tinyWizardCertificateRole').value = $('tinyWizardCertificateRole').value || exchangeOrg.certificate_role || 'template-package-signer';
    $('tinyWizardRootKeyId').value = $('tinyWizardRootKeyId').value || exchangeOrg.root_key_id || 'openmiura-org-root';
    $('tinyWizardCertificateKeyEpoch').value = $('tinyWizardCertificateKeyEpoch').value || String(exchangeOrg.certificate_key_epoch || 1);
    $('tinyWizardCertificateValidityDays').value = $('tinyWizardCertificateValidityDays').value || String((wizard.certificate_lifecycle || {}).certificate_validity_days || exchangeOrg.certificate_validity_days || 365);
    $('tinyWizardSyncTrustStoreOnCertificateLifecycle').checked = (wizard.certificate_lifecycle || {}).sync_trust_store !== false;
    $('tinyWizardPreviousSigningKeyIds').value = $('tinyWizardPreviousSigningKeyIds').value || ((exchangeOrg.previous_signing_key_ids || []).join(', '));
    $('tinyWizardPreviousSigningFingerprints').value = $('tinyWizardPreviousSigningFingerprints').value || ((exchangeOrg.previous_signing_fingerprints || []).join(', '));
    $('tinyWizardTrustedSignerFingerprints').value = $('tinyWizardTrustedSignerFingerprints').value || (((trustStore.trusted_signer_fingerprints || []).length ? trustStore.trusted_signer_fingerprints : (exchangeSigning.trusted_signer_fingerprints || [])).join(', '));
    $('tinyWizardTrustedOrganizationIds').value = $('tinyWizardTrustedOrganizationIds').value || (((trustStore.trusted_organization_ids || []).length ? trustStore.trusted_organization_ids : (exchangeOrg.trusted_organization_ids || [])).join(', '));
    $('tinyWizardTrustedOrgRootFingerprints').value = $('tinyWizardTrustedOrgRootFingerprints').value || (((trustStore.trusted_org_root_fingerprints || []).length ? trustStore.trusted_org_root_fingerprints : (exchangeOrg.trusted_org_root_fingerprints || [])).join(', '));
    $('tinyWizardDeniedPackageHashes').value = $('tinyWizardDeniedPackageHashes').value || ((trustDenylist.package_sha256 || []).join(', '));
    $('tinyWizardRevokedSignerFingerprints').value = $('tinyWizardRevokedSignerFingerprints').value || ((trustDenylist.signer_fingerprints || []).join(', '));
    $('tinyWizardRevokedSigningKeyIds').value = $('tinyWizardRevokedSigningKeyIds').value || ((trustDenylist.signing_key_ids || []).join(', '));
    $('tinyWizardRevokedOrganizationIds').value = $('tinyWizardRevokedOrganizationIds').value || ((trustDenylist.organization_ids || []).join(', '));
    $('tinyWizardRevokedOrgRootFingerprints').value = $('tinyWizardRevokedOrgRootFingerprints').value || ((trustDenylist.org_root_fingerprints || []).join(', '));
    $('tinyWizardRevokedCertificateFingerprints').value = $('tinyWizardRevokedCertificateFingerprints').value || ((trustDenylist.certificate_fingerprints || []).join(', '));
    $('tinyWizardRevokedCertificateIds').value = $('tinyWizardRevokedCertificateIds').value || ((trustDenylist.certificate_ids || []).join(', '));
    $('tinyWizardCertificateRevocationList').value = $('tinyWizardCertificateRevocationList').value || pretty(trustCrl.revoked_certificates || []);
    $('tinyWizardTrustStoreLevel').value = $('tinyWizardTrustStoreLevel').value || tinyState.wizard.selectedTrustStoreLevel || 'environment';

    renderWizardTemplateCategories();
    $('tinyWizardTemplateCategory').value = $('tinyWizardTemplateCategory').value || 'general';
    renderSigningProviders();
    if (!$('tinyWizardSigningProvider').value) $('tinyWizardSigningProvider').value = exchangeSigning.provider || 'local-ed25519';

    const providerSelect = $('tinyWizardLlmProvider');
    providerSelect.innerHTML = '';
    tinyState.wizard.providers.forEach((item) => {
      const option = document.createElement('option');
      option.value = item.provider_id;
      option.textContent = item.label;
      providerSelect.appendChild(option);
    });
    if (tinyState.wizard.providers.some((item) => item.provider_id === 'ollama')) {
      providerSelect.value = providerSelect.value || 'ollama';
      if (!providerSelect.value) providerSelect.value = 'ollama';
    }
    renderWizardTemplates();
    renderWizardTemplateLibrary();
    populateCertificateProfileOptions();
    populateImportApprovalOptions();
    populateTrustDecisionOptions();
    renderTrustStoreSummary();
    $('tinyWizardTemplateExchange').value = $('tinyWizardTemplateExchange').value || '';
    fillProviderDefaults({ force: true });
    syncTransportDefaults();
    syncProbeModeUi();
  }


  async function loadWizardDefaults({ silent = false } = {}) {
    try {
      const params = new URLSearchParams();
      const tenantId = $('tinyWizardTenantId') ? $('tinyWizardTenantId').value.trim() : '';
      const workspaceId = $('tinyWizardWorkspaceId') ? $('tinyWizardWorkspaceId').value.trim() : '';
      const environment = $('tinyWizardEnvironment') ? $('tinyWizardEnvironment').value.trim() : '';
      if (tenantId) params.set('tenant_id', tenantId);
      if (workspaceId) params.set('workspace_id', workspaceId);
      if (environment) params.set('environment', environment);
      const endpoint = `/admin/openclaw/tiny-runtime-wizard${params.toString() ? `?${params.toString()}` : ''}`;
      const payload = await api(endpoint);
      populateWizard(payload);
      if (($('tinyWizardTrustStoreLevel').value || 'environment') !== 'environment') {
        await refreshWizardTrustStore({ silent: true });
      }
      await refreshWizardImportApprovals({ silent: true });
      await refreshWizardTrustDecisions({ silent: true });
      updateWizardPreview();
      if (!silent) setStatus('Tiny runtime wizard defaults loaded.', 'ok');
      return payload;
    } catch (error) {
      if (!silent) setStatus(error.message, 'danger');
      throw error;
    }
  }

  async function testWizardConnection({ silent = false } = {}) {
    try {
      if (!tinyState.wizard.loaded) await loadWizardDefaults({ silent: true });
      const payload = updateWizardPreview();
      if (!payload.name.trim()) {
        setStatus('Runtime name is required.', 'danger');
        return null;
      }
      if (payload.transport === 'http' && !String(payload.base_url || '').trim()) {
        setStatus('Base URL is required for HTTP runtimes.', 'danger');
        return null;
      }
      const response = await api('/admin/openclaw/tiny-runtime-wizard/test-connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      tinyState.wizard.lastValidation = response.validation || null;
      $('tinyWizardResultBox').textContent = pretty(response);
      if (!silent) {
        const probe = (((response.validation || {}).chat_completion_probe) || {});
        const probeMode = ((probe.detail || {}).mode) || 'smoke';
        const successMessage = probe.status === 'passed'
          ? (probeMode === 'custom' ? 'Runtime, local LLM, and custom diagnostic probe validation passed.' : 'Runtime, local LLM, and smoke test validation passed.')
          : 'Runtime and local LLM validation passed.';
        const failureMessage = probe.status === 'failed'
          ? (probeMode === 'custom' ? 'Validation failed during the custom diagnostic chat probe.' : 'Validation failed during the smoke test chat probe.')
          : 'Validation failed. Fix the runtime or local LLM endpoint before registering.';
        setStatus(response.ok ? successMessage : failureMessage, response.ok ? 'ok' : 'danger');
      }
      return response;
    } catch (error) {
      if (!silent) setStatus(error.message, 'danger');
      $('tinyWizardResultBox').textContent = pretty({ ok: false, error: error.message });
      return null;
    }
  }

  async function registerWizardRuntime() {
    try {
      if (!tinyState.wizard.loaded) await loadWizardDefaults({ silent: true });
      const payload = updateWizardPreview();
      if (!payload.name.trim()) {
        setStatus('Runtime name is required.', 'danger');
        return;
      }
      if (payload.transport === 'http' && !String(payload.base_url || '').trim()) {
        setStatus('Base URL is required for HTTP runtimes.', 'danger');
        return;
      }
      const response = await api('/admin/openclaw/tiny-runtime-wizard/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      tinyState.wizard.lastValidation = response.validation || null;
      $('tinyWizardResultBox').textContent = pretty(response);
      if (!response.ok) {
        setStatus(response.message || 'Runtime registration blocked until validation passes.', 'danger');
        return;
      }
      tinyState.runtimeId = response.runtime?.runtime_id || tinyState.runtimeId;
      $('tinyRuntimeHint').textContent = 'Runtime registered from the Tiny wizard. Governance, dispatch, health, and replay are now available immediately.';
      setStatus(`Registered runtime ${response.runtime?.name || ''}`.trim(), 'ok');
      await loadRuntimes({ silent: true });
      if (tinyState.runtimeId) await loadRuntime(tinyState.runtimeId, { silent: true });
    } catch (error) {
      setStatus(error.message, 'danger');
      $('tinyWizardResultBox').textContent = pretty({ ok: false, error: error.message });
    }
  }

  async function copyWizardPreview() {
    try {
      await navigator.clipboard.writeText($('tinyWizardPreviewBox').textContent || '{}');
      setStatus('Tiny runtime preview copied.', 'ok');
    } catch (error) {
      setStatus(error.message, 'danger');
    }
  }

  async function loadRuntimes({ silent = false } = {}) {
    try {
      const response = await api('/admin/openclaw/runtimes?limit=200');
      const all = response.items || [];
      const tinyOnly = all.filter(isTinyRuntimeCandidate);
      const items = tinyOnly.length ? tinyOnly : all;
      tinyState.runtimes = items;
      if (!items.length) {
        tinyState.runtimeId = '';
        populateRuntimeSelect([]);
        $('tinyRuntimeHint').textContent = 'Register a governed runtime first. This console becomes useful as soon as a Tiny-OpenClaw compatible runtime is onboarded.';
        renderEmpty('tinyOverview', 'No runtime selected.');
        renderEmpty('tinyLlmCards', 'No local LLM profile yet.');
        renderEmpty('tinySkillsList', 'No declared skills.');
        renderEmpty('tinyBridgeList', 'No bridge information.');
        renderEmpty('tinyDispatchList', 'No dispatches.');
        renderEmpty('tinyTimelineList', 'No timeline.');
        $('tinyMetadataBox').textContent = '{}';
        if (!silent) setStatus('No governed runtimes found.', 'muted');
        return;
      }
      $('tinyRuntimeHint').textContent = tinyOnly.length
        ? 'Showing runtimes tagged or inferred as Tiny-OpenClaw compatible.'
        : 'No tiny-specific metadata was found, so all governed runtimes are shown.';
      if (!tinyState.runtimeId || !items.some((item) => item.runtime_id === tinyState.runtimeId)) {
        tinyState.runtimeId = items[0].runtime_id;
      }
      populateRuntimeSelect(items);
      await loadRuntime(tinyState.runtimeId, { silent });
    } catch (error) {
      if (!silent) setStatus(error.message, 'danger');
    }
  }

  async function loadRuntime(runtimeId, { silent = false } = {}) {
    if (!runtimeId) return;
    tinyState.runtimeId = runtimeId;
    try {
      const detail = await api(`/admin/openclaw/runtimes/${encodeURIComponent(runtimeId)}`);
      const timeline = await api(`/admin/openclaw/runtimes/${encodeURIComponent(runtimeId)}/timeline?limit=40`);
      tinyState.detail = detail;
      tinyState.timeline = timeline.timeline || [];
      renderOverview(detail);
      renderLocalLlm(detail);
      renderSimpleList(
        'tinySkillsList',
        normalizeSkills(detail).map((item) => ({ title: item })),
        'No skill declarations were found in runtime metadata.',
      );
      renderSimpleList('tinyBridgeList', normalizeBridges(detail), 'No bridge metadata was found.');
      renderDispatches(detail);
      renderTimeline(tinyState.timeline);
      $('tinyMetadataBox').textContent = pretty(detail.runtime || {});
      $('tinySessionId').value = $('tinySessionId').value || `tiny:${Date.now()}`;
      if (!silent) setStatus(`Loaded runtime ${detail.runtime?.name || runtimeId}`, 'ok');
    } catch (error) {
      if (!silent) setStatus(error.message, 'danger');
    }
  }

  async function runHealthCheck() {
    if (!tinyState.runtimeId) return;
    try {
      const payload = await api(`/admin/openclaw/runtimes/${encodeURIComponent(tinyState.runtimeId)}/health`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ probe: 'ready', session_id: $('tinySessionId').value || `tiny:${Date.now()}` }),
      });
      $('tinyDispatchBox').textContent = pretty(payload);
      setStatus(`Health: ${payload.health?.status || 'unknown'}`, payload.health?.status === 'healthy' ? 'ok' : 'muted');
      await loadRuntime(tinyState.runtimeId, { silent: true });
    } catch (error) {
      setStatus(error.message, 'danger');
    }
  }

  async function dispatchChat() {
    if (!tinyState.runtimeId) return;
    const message = $('tinyMessageInput').value.trim();
    if (!message) {
      setStatus('Write a message before dispatching.', 'danger');
      return;
    }
    const sessionId = $('tinySessionId').value.trim() || `tiny:${Date.now()}`;
    $('tinySessionId').value = sessionId;
    try {
      const payload = await api(`/admin/openclaw/runtimes/${encodeURIComponent(tinyState.runtimeId)}/dispatch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'chat',
          session_id: sessionId,
          agent_id: $('tinyAgentId').value.trim() || undefined,
          dry_run: !!$('tinyDryRunToggle').checked,
          payload: { message },
        }),
      });
      $('tinyDispatchBox').textContent = pretty(payload);
      $('tinyMessageInput').value = '';
      setStatus(`Dispatch ${payload.dispatch?.canonical_status || payload.dispatch?.status || 'submitted'}`, 'ok');
      await loadRuntime(tinyState.runtimeId, { silent: true });
    } catch (error) {
      setStatus(error.message, 'danger');
    }
  }

  async function copyMetadata() {
    try {
      await navigator.clipboard.writeText($('tinyMetadataBox').textContent || '{}');
      setStatus('Runtime metadata copied.', 'ok');
    } catch (error) {
      setStatus(error.message, 'danger');
    }
  }

  function bind() {
    $('tinyRefreshBtn').onclick = () => loadRuntimes();
    $('tinyLoadRuntimeBtn').onclick = () => loadRuntime($('tinyRuntimeSelect').value);
    $('tinyHealthBtn').onclick = runHealthCheck;
    $('tinyDispatchBtn').onclick = dispatchChat;
    $('tinyRefreshDispatchesBtn').onclick = () => loadRuntime(tinyState.runtimeId);
    $('tinyRefreshTimelineBtn').onclick = () => loadRuntime(tinyState.runtimeId);
    $('tinyRuntimeSelect').onchange = () => {
      tinyState.runtimeId = $('tinyRuntimeSelect').value;
      loadRuntime(tinyState.runtimeId);
    };
    $('tinyCopyMetadataBtn').onclick = copyMetadata;

    $('tinyWizardRefreshBtn').onclick = () => loadWizardDefaults();
    $('tinyWizardLoadTemplateBtn').onclick = () => {
      const selected = (tinyState.wizard.templates || []).find((item) => item.template_id === $('tinyWizardTemplateSelect').value);
      if (!selected) {
        setStatus('Choose a saved template first.', 'danger');
        return;
      }
      applyTemplateToWizard(selected);
    };
    $('tinyWizardRefreshCertificateProfilesBtn').onclick = () => refreshWizardCertificateProfiles();
    $('tinyWizardLoadCertificateProfileBtn').onclick = () => {
      const selected = selectedCertificateProfile();
      if (!selected) {
        setStatus('Choose a certificate profile first.', 'danger');
        return;
      }
      applyCertificateProfileToWizard(selected);
      setStatus(`Loaded certificate profile ${selected.profile_name || selected.profile_id}.`, 'ok');
    };
    $('tinyWizardIssueCertificateProfileBtn').onclick = issueWizardCertificateProfile;
    $('tinyWizardRotateCertificateProfileBtn').onclick = rotateWizardCertificateProfile;
    $('tinyWizardRevokeCertificateProfileBtn').onclick = revokeWizardCertificateProfile;
    $('tinyWizardSaveTemplateBtn').onclick = saveWizardTemplate;
    $('tinyWizardCloneTemplateBtn').onclick = cloneWizardTemplate;
    $('tinyWizardUpdateTemplateBtn').onclick = updateWizardTemplate;
    $('tinyWizardDeleteTemplateBtn').onclick = deleteWizardTemplate;
    $('tinyWizardSaveTrustStoreBtn').onclick = saveWizardTrustStore;
    $('tinyWizardRefreshImportApprovalsBtn').onclick = () => refreshWizardImportApprovals();
    $('tinyWizardApproveImportBtn').onclick = () => decideWizardImportApproval('approve');
    $('tinyWizardRejectImportBtn').onclick = () => decideWizardImportApproval('reject');
    $('tinyWizardRefreshTrustDecisionsBtn').onclick = () => refreshWizardTrustDecisions();
    $('tinyWizardReplayTrustDecisionBtn').onclick = () => replayTrustDecision();
    $('tinyWizardExportTemplatesBtn').onclick = exportWizardTemplates;
    $('tinyWizardImportTemplatesBtn').onclick = importWizardTemplates;
    $('tinyWizardPreviewBtn').onclick = () => {
      updateWizardPreview();
      setStatus('Tiny runtime preview refreshed.', 'ok');
    };
    $('tinyWizardTestConnectionBtn').onclick = () => testWizardConnection();
    $('tinyWizardRegisterBtn').onclick = registerWizardRuntime;
    $('tinyWizardCopyPreviewBtn').onclick = copyWizardPreview;
    $('tinyWizardTransport').onchange = syncTransportDefaults;
    $('tinyWizardPolicyPack').onchange = updateWizardPreview;
    $('tinyWizardLlmProvider').onchange = () => {
      fillProviderDefaults({ force: true });
      updateWizardPreview();
    };
    [
      'tinyWizardName',
      'tinyWizardBaseUrl',
      'tinyWizardAuthSecretRef',
      'tinyWizardTenantId',
      'tinyWizardWorkspaceId',
      'tinyWizardEnvironment',
      'tinyWizardAllowedAgents',
      'tinyWizardSkills',
      'tinyWizardLlmModel',
      'tinyWizardLlmBaseUrl',
      'tinyWizardApiStyle',
      'tinyWizardStateStorage',
      'tinyWizardChatProbePrompt',
      'tinyWizardChatProbeExpectedContent',
      'tinyWizardCapabilities',
      'tinyWizardTemplateName',
      'tinyWizardTemplateCategory',
      'tinyWizardCertificateProfileName',
      'tinyWizardCertificateValidityDays',
      'tinyWizardSigningKeyId',
      'tinyWizardTrustedSignerFingerprints',
    ].forEach((id) => {
      $(id).addEventListener('input', () => updateWizardPreview());
    });
    ['tinyWizardSessionBridge', 'tinyWizardEventBridge', 'tinyWizardStateBridge', 'tinyWizardChatProbeEnabled', 'tinyWizardChatProbeMode', 'tinyWizardTemplateSelect', 'tinyWizardTemplateCategory', 'tinyWizardSignPackage', 'tinyWizardRequireSignature', 'tinyWizardSigningProvider', 'tinyWizardSyncTrustStoreOnCertificateLifecycle'].forEach((id) => {
      $(id).addEventListener('change', () => updateWizardPreview());
    });
    $('tinyWizardTrustStoreLevel').addEventListener('change', () => {
      tinyState.wizard.selectedTrustStoreLevel = $('tinyWizardTrustStoreLevel').value || 'environment';
      refreshWizardTrustStore({ silent: true }).catch((error) => setStatus(error.message, 'danger'));
    });
    $('tinyWizardCertificateProfileSelect').addEventListener('change', () => {
      const selected = selectedCertificateProfile();
      $('tinyWizardCertificateProfileBox').textContent = pretty(selected || {});
    });
    $('tinyWizardImportApprovalSelect').addEventListener('change', () => {
      const selected = (tinyState.wizard.importApprovals || []).find((item) => item.approval_id === $('tinyWizardImportApprovalSelect').value) || null;
      $('tinyWizardImportApprovalBox').textContent = pretty(selected || {});
    });
    $('tinyWizardTrustDecisionSelect').addEventListener('change', () => {
      const selected = (tinyState.wizard.trustDecisions || []).find((item) => item.decision_id === $('tinyWizardTrustDecisionSelect').value) || null;
      $('tinyWizardTrustDecisionBox').textContent = pretty(selected || {});
    });
    $('tinyWizardChatProbeMode').addEventListener('change', () => {
      syncProbeModeUi();
      updateWizardPreview();
    });

    document.querySelectorAll('.tab-btn[data-tab="tiny"]').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (!tinyState.wizard.loaded) loadWizardDefaults({ silent: true }).catch(() => {});
        if (!tinyState.runtimes.length) {
          loadRuntimes({ silent: true });
        } else if (tinyState.runtimeId) {
          loadRuntime(tinyState.runtimeId, { silent: true });
        }
      });
    });
  }

  bind();
  if (new URLSearchParams(location.search).get('tab') === 'tiny') {
    loadWizardDefaults({ silent: true }).catch(() => {});
    loadRuntimes({ silent: true });
  }
})();
