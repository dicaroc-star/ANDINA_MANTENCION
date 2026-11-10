'use strict';
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
let user = null, csrf = '', metadata = {}, lookups = {}, current = 'dashboard', rows = [], page = 1, total = 0;
let editing = null, generation = 0, listGeneration = 0, searchTimer;
let pendingReport = new URLSearchParams(location.search || '').get('reportar');
let reportRequested = new URLSearchParams(location.search || '').get('accion')==='reportar';
let qrReportActive = false;
let reportReceipt = null;
const names = {id_usuario:'Reportado / registrado por',fecha_reporte:'Fecha de reporte',fecha_creacion:'Fecha de creación',fecha_consumo:'Fecha de consumo',id_orden:'Orden',estado_anterior:'Estado anterior',estado_nuevo:'Estado nuevo',fecha_cambio:'Fecha del cambio',observaciones:'Observaciones'};
const relationNames = {id_usuario:'usuario',id_orden:'orden_trabajo'};
const menuOrder = ['activo','ubicacion','incidencia','orden_trabajo','intervencion','repuesto','consumo_repuesto','mantenimiento_preventivo','historial_estado','usuario','rol'];

const navPaths={dashboard:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',activo:'M4 7h16v13H4z M8 7V4h8v3 M8 12h8',ubicacion:'M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z M12 7v6 M9 10h6',incidencia:'M12 3 2 21h20L12 3Z M12 9v5 M12 17v1',orden_trabajo:'M8 5H5v16h14V5h-3 M8 3h8v5H8z M8 12h8 M8 16h5',intervencion:'M14 6a5 5 0 0 0-6 6L3 17l4 4 5-5a5 5 0 0 0 6-6l-3 3-4-4 3-3Z',repuesto:'M3 7 12 3l9 4v11l-9 4-9-4V7Z M3 7l9 4 9-4 M12 11v11',consumo_repuesto:'M4 6h16v14H4z M8 3v6 M16 3v6 M8 14h8',mantenimiento_preventivo:'M4 5h16v16H4z M8 2v6 M16 2v6 M4 10h16 M8 15l3 3 5-5',historial_estado:'M3 12a9 9 0 1 0 3-7 M3 3v6h6 M12 7v6l4 2',usuario:'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z M4 22v-3a8 8 0 0 1 16 0v3',rol:'M12 2 3 6v7c0 5 9 9 9 9s9-4 9-9V6l-9-4Z M8 12l3 3 5-6'};
function navIcon(key){return `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${navPaths[key]||navPaths.activo}"/></svg>`;}
function stateBadge(value){const safe=String(value??'');const tone=['OPERATIVO','RESUELTA','FINALIZADA'].includes(safe)?'good':['ALTA','CRITICA','DETENIDO'].includes(safe)?'danger':['EN_PROCESO','MANTENIMIENTO','MEDIA','ASIGNADA'].includes(safe)?'warning':'neutral';return `<span class="state-badge ${tone}"><span aria-hidden="true"></span>${esc(safe.replaceAll('_',' '))}</span>`;}
async function api(path, data) {
  let response;
  try {
    response = await fetch(path, {method: data === undefined ? 'GET' : 'POST', credentials:'same-origin', cache:'no-store',
      headers: data === undefined ? {} : {'Content-Type':'application/json','X-CSRF-Token':csrf},
      body: data === undefined ? undefined : JSON.stringify(data)});
  } catch (_) { throw new Error('No se pudo contactar al servidor. Revisa tu conexión y vuelve a intentarlo.'); }
  let result;
  try { result = await response.json(); } catch (_) { throw new Error('El servidor no devolvió una respuesta válida. Actualiza la página y vuelve a intentarlo.'); }
  if (!response.ok) {
    if(response.status === 401 && user) leave();
    throw new Error(result.error || 'No se pudo completar la operación.');
  }
  return result;
}
function notify(message, error = false) {
  $('#message').hidden=false; $('#message').textContent=message; $('#message').classList.toggle('failure',error);
}
function leave() {
  resetReportPhotos();
  reportReceipt=null;
  qrReportActive=false;
  user=null; csrf=''; metadata={}; lookups={}; rows=[]; generation++; listGeneration++;
  document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());
  $('#app').hidden=true; $('#login').hidden=false; $('#content').replaceChildren(); $('#navigation').replaceChildren();
  $('#password').value=''; $('#password').type='password'; $('#toggle-password').innerHTML=stitchSymbol('visibility'); $('#toggle-password').setAttribute('aria-pressed','false');
  $('#email').focus();
  updateLoginIntent();
}
async function enter(result) {
  user=result.user; csrf=result.csrf;
  [metadata,lookups]=await Promise.all([api('/api/meta'),api('/api/lookups')]);
  $('#profile-name').textContent=`${user.nombre} ${user.apellido}`;
  $('#profile-role').textContent=user.rol; $('#avatar').textContent=(user.nombre[0]||'')+(user.apellido[0]||'');
  $('#navigation').innerHTML=stitchNavigation(metadata);
  $('#nav-report-failure')?.addEventListener('click',reportFailure);
  $('#navigation').querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>render(button.dataset.view)));
  $('#login').hidden=true; $('#app').hidden=false; $('#message').hidden=true;
  $('#connection-status').textContent='● Oracle conectado';
  await render('dashboard');
  if(pendingReport)await continueQrReport();
  else if(reportRequested)await reportFailure();
}

function updateLoginIntent() {
  const reporting=Boolean(pendingReport||reportRequested);
  $('#login-title').textContent=reporting?'Inicia sesión para reportar':'Bienvenido';
  $('#report-login-note').hidden=!reporting;
  $('#login-submit').innerHTML=(reporting?'Entrar y reportar':'Iniciar sesión')+stitchSymbol('arrow_forward','text-base');
}
function clearReportRequest() {
  reportRequested=false;
  const params=new URLSearchParams(location.search||'');params.delete('accion');
  history.replaceState(null,'',location.pathname+(params.size?'?'+params.toString():'')+(location.hash||''));
  updateLoginIntent();
}
$('#public-report-failure').addEventListener('click',async()=>{
  reportRequested=true;
  const params=new URLSearchParams(location.search||'');params.set('accion','reportar');
  history.replaceState(null,'',location.pathname+'?'+params.toString()+(location.hash||''));
  updateLoginIntent();
  if(user)await reportFailure();
  else {$('#email').focus();$('#email').scrollIntoView?.({behavior:'smooth',block:'center'});}
});

function finishQrReport() {
  pendingReport=null;qrReportActive=false;
  clearReportRequest();
  const params=new URLSearchParams(location.search || '');params.delete('reportar');
  const query=params.toString();
  history.replaceState(null,'',location.pathname+(query?'?'+query:'')+(location.hash||''));
  $('#server-hint').textContent='Tu acceso depende de los permisos asignados a tu cuenta.';
}
async function continueQrReport() {
  if(!pendingReport || !user)return;
  if(pendingReport.length>30 || /[\x00-\x1f\x7f]/.test(pendingReport)) {
    finishQrReport();notify('El código del QR no es válido. Solicita una etiqueta nueva al administrador.',true);return;
  }
  if(!metadata.incidencia?.writable) {
    finishQrReport();notify('Tu cuenta no tiene permiso para reportar incidencias.',true);return;
  }
  // El ID se obtiene de Oracle después de autenticar; el QR contiene solo codigo_activo.
  const asset=lookups.activo.find(item=>item.codigo_activo===pendingReport);
  if(!asset) {
    finishQrReport();notify('No se encontró el activo del QR. No se creó ningún reporte.',true);return;
  }
  if(asset.estado==='INACTIVO'){
    finishQrReport();notify('El activo de este QR está inactivo. Contacta al responsable de mantenimiento.',true);return;
  }
  await render('incidencia');
  if(!user || current!=='incidencia')return;
  const opened=await openEditor(null,{id_activo:asset.id,estado:'REPORTADA'});
  if(opened) {
    clearReportRequest();
    qrReportActive=true;
    $('#field-id_activo').value=String(asset.id);
    $('#editor-note').textContent=`Activo del QR: ${asset.codigo_activo} · ${asset.label}. Describe la falla y revisa la prioridad antes de guardar.`;
    $('#field-descripcion').focus();
  }
}
async function reportFailure(event) {
  if(!user)return;
  if(!metadata.incidencia?.writable){clearReportRequest();notify('Tu cuenta no tiene permiso para reportar incidencias.',true);return;}
  const trigger=event?.currentTarget;
  if(trigger)trigger.disabled=true;
  try {
    if(pendingReport){await continueQrReport();return;}
    await render('incidencia');
    if(!user || current!=='incidencia' || !$('#new-record'))return;
    const opened=await openEditor(null,{estado:'REPORTADA'});
    if(opened){
      clearReportRequest();
      $('#editor-title').textContent='Reportar falla';
      $('#editor-note').textContent='Selecciona el activo, describe lo que ocurre y revisa la prioridad. Al enviar recibirás el código de tu incidencia.';
      $('#field-id_activo').focus();
    }
  }catch(error){if(user)notify(error.message,true);}
  finally{if(trigger)trigger.disabled=false;}
}
function reportShortcut() {
  if(!metadata.incidencia?.writable)return '';
  return '<section class="report-hero" aria-labelledby="report-heading"><div class="report-symbol" aria-hidden="true">!</div><div class="report-copy"><span class="report-eyebrow">REPORTE DE FALLAS</span><h2 id="report-heading">¿Notaste una falla en un equipo?</h2><p>Repórtala aquí para que el equipo de mantenimiento pueda revisarla.</p></div><button id="dashboard-report-failure" class="report-action">Reportar una falla <span aria-hidden="true">→</span></button></section>';
}
$('#login-form').addEventListener('submit',async event=>{
  event.preventDefault(); $('#login-submit').disabled=true; $('#login-error').textContent='';
  try { const result=await api('/api/login',{correo:$('#email').value.trim(),password:$('#password').value}); $('#password').value=''; await enter(result); }
  catch(error) { leave(); $('#login-error').textContent=error.message; }
  finally { $('#login-submit').disabled=false; }
});
$('#toggle-password').addEventListener('click',()=>{const show=$('#password').type==='password';$('#password').type=show?'text':'password';$('#toggle-password').innerHTML=stitchSymbol(show?'visibility_off':'visibility');$('#toggle-password').setAttribute('aria-pressed',String(show));});
$('#logout').addEventListener('click',async()=>{try { await api('/api/logout',{}); leave(); $('#login-error').textContent=''; } catch(error){notify(error.message,true);} });

function title(table) {return table==='dashboard'?'Panel principal':metadata[table].title;}
function heading(table,description) {return `<div class="page-heading"><div><span class="eyebrow">ANDINAMANTENCIÓN</span><h1>${esc(title(table))}</h1><p>${esc(description)}</p></div><button class="secondary" id="refresh">Actualizar ↻</button></div>`;}
function fieldLabel(table,column) {return metadata[table]?.fields.find(field=>field.name===column)?.label || names[column] || (column.startsWith('id_')?'ID':column.replaceAll('_',' '));}
function display(table,column,value) {
  if(value===null || value===undefined || value==='') return '—';
  const field=metadata[table]?.fields.find(item=>item.name===column);
  const reference=field?.table || relationNames[column];
  if(reference) { const match=lookups[reference]?.find(item=>Number(item.id)===Number(value)); return match?`#${value} · ${match.label}`:`#${value}`; }
  if(column.startsWith('fecha_')) return String(value).replace('T',' ').slice(0,19);
  return String(value);
}
async function render(table) {
  if(!user) return;
  const request=++generation; ++listGeneration; clearTimeout(searchTimer); current=table; page=1;
  $('#breadcrumb').textContent=title(table);
  document.querySelectorAll('[data-view]').forEach(button=>{button.classList.toggle('active',button.dataset.view===table);if(button.dataset.view===table)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});
  $('#content').innerHTML='<p class="empty" role="status">Consultando Oracle…</p>';
  try {
    if(table==='dashboard') {
      const dashboard=await api('/api/dashboard'); if(request!==generation)return;
      $('#content').innerHTML=stitchDashboard(dashboard);
      const alerts=dashboard.alertas_preventivos||[];
      const alertsMarkup=alerts.map(alert=>{
        const date=String(alert.fecha_programada||'').slice(0,10);
        const type=alert.tipo_alerta==='Vencido'?'Vencido':'Próximo';
        const label=type==='Vencido'?'danger':'warning';
        const responsible=[alert.responsable_nombre,alert.responsable_apellido].filter(Boolean).join(' ')||'Sin responsable registrado';
        return `<li class="p-3 border-b border-outline-variant/20 flex flex-wrap items-center justify-between gap-2"><div><strong>${esc(alert.codigo_activo)}</strong> · ${esc(alert.descripcion)}<p class="muted small">Fecha: ${esc(date)} · ${esc(responsible)}</p></div><span class="state-badge ${label}">${type}</span></li>`;
      }).join('');
      $('#content').insertAdjacentHTML('beforeend',`<section class="card p-5 mt-5" aria-labelledby="sprint2-alerts-title"><div class="flex items-center justify-between flex-wrap gap-3"><div><h2 id="sprint2-alerts-title" class="font-headline-md font-semibold">Alertas de mantenimiento preventivo</h2><p class="muted small">Vencidos y próximos 7 días · ${alerts.length===25?'Mostrando hasta 25 registros':''+alerts.length+' registro(s)'}</p></div><button id="open-preventive-alerts" class="secondary" type="button">Ver mantenimientos</button></div>${alerts.length?'<ul class="mt-3">'+alertsMarkup+'</ul>':'<p class="empty">No hay preventivos vencidos ni próximos a vencer.</p>'}</section>`);
      $('#open-preventive-alerts')?.addEventListener('click',()=>render('mantenimiento_preventivo'));
      $('#dashboard-report-failure')?.addEventListener('click',reportFailure);
      $('#open-incidents').addEventListener('click',()=>render('incidencia'));
      document.querySelectorAll('[data-dashboard-incident]').forEach(button=>button.addEventListener('click',async()=>{
        const identifier=Number(button.dataset.dashboardIncident);await render('incidencia');
        if(current!=='incidencia'||!user)return;
        const found=await api('/api/records/incidencia?page=1&q='+encodeURIComponent(identifier)+'&state=');
        const record=found.rows.find(row=>Number(row.id_incidencia)===identifier);
        if(record)openDetail(record);else notify('El registro ya no está disponible.',true);
      }));
    } else {
      const spec=metadata[table];
      const states=spec.fields.find(field=>field.name==='estado')?.options;
      $('#content').innerHTML=heading(table,table==='historial_estado'?'Trazabilidad automática de los estados de las órdenes.':'Consulta, busca y gestiona los registros de este módulo.')+`<div class="filters"><div><label for="search">Buscar por ID o texto</label><input id="search" type="search" placeholder="Escribe para buscar…" maxlength="150"></div>${states?`<div><label for="state-filter">Estado</label><select id="state-filter"><option value="">Todos</option>${states.map(state=>`<option>${state}</option>`).join('')}</select></div>`:''}<button id="clear" class="secondary">Limpiar</button>${spec.writable?'<button id="new-record" class="primary">+ Nuevo registro</button>':''}</div><section class="card"><div id="records" aria-live="polite"></div><div class="pagination"><span id="page-info"></span><div><button id="previous" class="secondary">← Anterior</button><button id="next" class="secondary">Siguiente →</button></div></div></section><p class="muted small">${table==='consumo_repuesto'?'Al guardar se descuenta stock. Al corregir un consumo se ajusta la diferencia en la misma transacción.':table==='usuario'?'Solo administradores. Una contraseña vacía conserva la actual al editar. Guardar cierra las sesiones de ese usuario.':table==='orden_trabajo'?'Flujo: PENDIENTE → ASIGNADA → EN_PROCESO → FINALIZADA. También puedes cancelar una orden no finalizada.':'Los registros se conservan para mantener sus relaciones. Usa los estados disponibles para desactivar o cancelar.'}</p>`;
      if(table==='orden_trabajo'){
        let markup=$('#content').innerHTML;
        markup=markup.slice(markup.indexOf('<div class="filters">')).replace('<button id="new-record" class="primary">+ Nuevo registro</button>','');
        let original=stitchOrderSummary().replace('id="new-order-from-model"','id="new-record"');
        if(!spec.writable)original=original.replace('id="new-record"','id="new-record" hidden');
        $('#content').innerHTML=original+markup+'<button type="button" id="refresh" hidden>Actualizar</button>';
        $('#export-orders').addEventListener('click',()=>{
          const blob=new Blob([JSON.stringify(rows,null,2)],{type:'application/json;charset=utf-8'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='ordenes-de-trabajo.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
        });
      }
      $('#search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{page=1;loadRows();},300);});
      $('#state-filter')?.addEventListener('change',()=>{page=1;loadRows();});
      $('#clear').addEventListener('click',()=>{$('#search').value='';if($('#state-filter'))$('#state-filter').value='';page=1;loadRows();});
      $('#previous').addEventListener('click',()=>{page--;loadRows();}); $('#next').addEventListener('click',()=>{page++;loadRows();});
      $('#new-record')?.addEventListener('click',()=>openEditor(null));
      await loadRows();
    }
    if(request!==generation)return;
    $('#refresh').addEventListener('click',async()=>{try {lookups=await api('/api/lookups');await render(current);}catch(error){notify(error.message,true);}});
    $('#connection-status').textContent='● Oracle conectado'; $('#content').focus();
  } catch(error) {if(request===generation && user){$('#content').innerHTML='<p class="empty">No se pudo cargar este módulo. Usa su botón en el menú para reintentar.</p>';notify(error.message,true);$('#connection-status').textContent='● No se pudo consultar Oracle';}}
}
const preferredColumns={activo:['codigo_activo','nombre','estado','id_ubicacion'],usuario:['nombre','apellido','correo','estado','id_rol'],incidencia:['id_activo','descripcion','prioridad','estado'],orden_trabajo:['id_incidencia','id_usuario_asignado','estado','fecha_creacion'],intervencion:['id_orden','diagnostico','fecha_inicio','fecha_fin'],repuesto:['codigo_repuesto','nombre','stock_actual','stock_minimo','estado'],consumo_repuesto:['id_intervencion','id_repuesto','cantidad','precio_unitario'],mantenimiento_preventivo:['id_activo','id_usuario_responsable','fecha_programada','estado'],historial_estado:['id_orden','id_usuario','estado_anterior','estado_nuevo','fecha_cambio']};
async function loadRows() {
  const table=current, request=++listGeneration; const container=$('#records');if(!container)return;
  $('#previous').disabled=true;$('#next').disabled=true;container.innerHTML='<p class="empty">Consultando…</p>';
  try {
    const params=new URLSearchParams({page:String(page),q:$('#search').value,state:$('#state-filter')?.value||''});
    const result=await api(`/api/records/${table}?${params}`);
    if(request!==listGeneration || table!==current || !user)return;
    rows=result.rows;total=result.total;
    const spec=metadata[table], cols=[spec.pk,...(preferredColumns[table]||spec.fields.map(field=>field.name))];
    container.innerHTML=(table==='orden_trabajo'&&rows.length)?stitchOrderRows(rows):rows.length?`<div class="table-scroll"><table><thead><tr>${cols.map(col=>`<th>${esc(fieldLabel(table,col))}</th>`).join('')}<th>Acciones</th></tr></thead><tbody>${rows.map((row,index)=>`<tr>${cols.map(col=>`<td class="wrap" title="${esc(display(table,col,row[col]))}">${['estado','prioridad'].includes(col)?stateBadge(row[col]):esc(display(table,col,row[col]))}</td>`).join('')}<td><div class="row-actions"><button class="text-button" data-detail="${index}">Detalle</button>${canEdit(table,row)?`<button class="text-button" data-edit="${index}">Editar</button>`:''}</div></td></tr>`).join('')}</tbody></table></div>`:'<p class="empty">No hay registros que coincidan con estos filtros.</p>';
    container.querySelectorAll('[data-detail]').forEach(button=>button.addEventListener('click',()=>openDetail(rows[Number(button.dataset.detail)])));
    container.querySelectorAll('[data-edit]').forEach(button=>button.addEventListener('click',()=>openEditor(rows[Number(button.dataset.edit)])));
    $('#page-info').textContent=`${total} registros · Página ${page} de ${Math.max(1,Math.ceil(total/25))}`;
    $('#previous').disabled=page<=1;$('#next').disabled=page*25>=total;
  }catch(error){if(request===listGeneration && user){container.innerHTML='<p class="empty">No se pudieron cargar los registros.</p>';notify(error.message,true);}}
}
function canEdit(table,row) {
  if(!metadata[table].editable)return false;
  if(['OPERADOR','TECNICO'].includes(user.rol) && table==='incidencia')return row.id_usuario===user.id_usuario && row.estado==='REPORTADA';
  if(user.rol==='TECNICO') {
    if(table==='intervencion')return row.id_usuario===user.id_usuario && lookups.orden_trabajo.some(order=>order.id===row.id_orden&&order.id_usuario_asignado===user.id_usuario&&order.estado==='EN_PROCESO');
    if(table==='consumo_repuesto'){const intervention=lookups.intervencion.find(item=>item.id===row.id_intervencion);return intervention?.id_usuario===user.id_usuario && lookups.orden_trabajo.some(order=>order.id===intervention.id_orden&&order.id_usuario_asignado===user.id_usuario&&order.estado==='EN_PROCESO');}
  }
  return true;
}
function openDetail(row) {
  const spec=metadata[current];$('#detail-title').textContent=`${spec.title} · #${row[spec.pk]}`;
  $('#detail-content').classList.toggle('order-detail',current==='orden_trabajo');
  $('#detail-content').innerHTML=current==='orden_trabajo'?stitchOrderDetail(row):'<dl class="record-detail-data">'+spec.columns.map(col=>`<dt>${esc(fieldLabel(current,col))}</dt><dd>${esc(display(current,col,row[col]))}</dd>`).join('')+'</dl>';
  if(current==='incidencia'){
    $('#detail-content').innerHTML+='<section id="incident-photos" class="incident-photos" aria-live="polite">Cargando fotografías…</section>';
    loadIncidentPhotos(row.id_incidencia);
  }
  if(current==='activo')$('#detail-content').innerHTML+=`<section class="asset-qr"><h3>QR del activo</h3><p>Escanea para reportar una falla de este equipo.</p><img src="/api/activos/${Number(row.id_activo)}/qr" alt="QR del activo ${esc(row.codigo_activo)}"><strong>${esc(row.codigo_activo)}</strong><div><a class="primary" href="/api/activos/${Number(row.id_activo)}/qr" download="QR-${esc(row.codigo_activo)}.png">Descargar QR</a><a class="secondary" href="/?reportar=${encodeURIComponent(row.codigo_activo)}">Abrir reporte</a></div></section>`;
  $('#detail').showModal();
}
function optionsFor(field,row) {
  let list=lookups[field.table]||[];
  // Conserva referencias existentes aunque cambien de estado; el servidor valida al guardar.
  if(field.table==='usuario')list=list.filter(item=>item.estado==='ACTIVO'||item.id===row?.[field.name]);
  if(field.table==='repuesto')list=list.filter(item=>item.estado==='ACTIVO'||item.id===row?.[field.name]);
  if(user.rol==='TECNICO' && field.table==='orden_trabajo')list=list.filter(item=>item.id_usuario_asignado===user.id_usuario&&item.estado==='EN_PROCESO');
  if(user.rol==='TECNICO' && field.table==='intervencion')list=list.filter(item=>item.id_usuario===user.id_usuario&&lookups.orden_trabajo.some(order=>order.id===item.id_orden&&order.id_usuario_asignado===user.id_usuario&&order.estado==='EN_PROCESO'));
  return list;
}
async function openEditor(row,preset={}) {
  resetReportPhotos();
  const table=current;
  $('#save-record').disabled=false;
  try{lookups=await api('/api/lookups');}catch(error){notify(error.message,true);return;}
  if(current!==table || !user)return;
  editing=row; const spec=metadata[table];$('#record-form').reset();$('#form-error').textContent='';
  $('#editor-title').textContent=`${row?'Editar':'Nuevo registro'} · ${spec.title}`;
  $('#editor').classList.toggle('report-editor',table==='incidencia'&&!row);
  $('#save-record').textContent=table==='incidencia'&&!row?'Enviar reporte a mantenimiento →':'Guardar cambios';
  $('#editor-note').textContent=table==='consumo_repuesto'?'El stock se ajustará al guardar. No se permite stock negativo.':table==='orden_trabajo'?'Cada cambio de estado se registra en el historial. Completa las fechas al iniciar o finalizar.':'Completa los datos del registro. Los campos con * son obligatorios.';
  $('#fields').innerHTML=spec.fields.map(field=>{
    const name=field.name,id='field-'+name;let value=row?.[name]??preset[name]??field.default??'';
    if(field.kind==='date')value=String(value).slice(0,10);
    if(field.kind==='datetime')value=String(value).slice(0,19);
    const required=field.required?'required':'';let control;
    if(field.kind==='ref')control=`<select id="${id}" name="${name}" ${required}><option value="">Selecciona…</option>${optionsFor(field,row).map(item=>`<option value="${item.id}" ${Number(value)===Number(item.id)?'selected':''}>#${item.id} · ${esc(item.label)}${item.stock_actual===undefined?'':` · stock ${esc(item.stock_actual)}`}</option>`).join('')}</select>`;
    else if(field.kind==='select') {
      let choices=field.options;
      if(table==='incidencia'&&field.name==='estado'&&!metadata.incidencia.editable)choices=['REPORTADA'];
      if(table==='orden_trabajo'&&field.name==='estado') {const next={PENDIENTE:['ASIGNADA','CANCELADA'],ASIGNADA:['PENDIENTE','EN_PROCESO','CANCELADA'],EN_PROCESO:['FINALIZADA','CANCELADA'],FINALIZADA:[],CANCELADA:[]};choices=row?[row.estado,...(next[row.estado]||[])]:['PENDIENTE','ASIGNADA'];}
      control=`<select id="${id}" name="${name}" ${required}>${choices.map(option=>`<option ${value===option?'selected':''}>${esc(option)}</option>`).join('')}</select>`;
    } else if(field.kind==='text'&&field.length>=500)control=`<textarea id="${id}" name="${name}" maxlength="${field.length}" rows="3" ${required}>${esc(value)}</textarea>`;
    else {const type={integer:'number',money:'number',datetime:'datetime-local',date:'date',email:'email'}[field.kind]||'text';control=`<input id="${id}" name="${name}" type="${type}" value="${esc(value)}" ${required} ${field.length?`maxlength="${field.length}"`:''} ${field.minimum===undefined?'':`min="${field.minimum}" max="${field.maximum}"`} ${['money','integer','datetime'].includes(field.kind)?`step="${field.kind==='money'?'.01':'1'}"`:''}>`;}
    return `<div class="${field.length>=500?'span-two':''} field-${name}"><label for="${id}">${esc(field.label)}${field.required?' *':''}</label>${control}</div>`;
  }).join('')+(table==='usuario'?`<div class="span-two"><label for="field-password">${row?'Nueva contraseña (vacía para conservar)':'Contraseña inicial *'}</label><input id="field-password" name="password" type="password" autocomplete="new-password" minlength="12" maxlength="128" ${row?'':'required'}><small>Entre 12 y 128 caracteres. El servidor guarda solo su hash.</small></div>`:'');
  if(table==='incidencia'&&!row){
    $('#editor-title').textContent='Reportar una falla técnica';
    $('#fields').innerHTML=stitchReportFields(preset);
    initializePhotoPicker();
    $('#field-id_activo').addEventListener('change',()=>{$('#report-location').value=stitchAssetLocation($('#field-id_activo').value);});
    $('#editor-note').textContent='Describe lo que ocurre para que mantenimiento pueda revisar el equipo.';
  }
  if(table==='consumo_repuesto' && !row){$('#field-id_repuesto').addEventListener('change',()=>{const item=lookups.repuesto.find(item=>String(item.id)===$('#field-id_repuesto').value);$('#field-precio_unitario').value=item?.precio_unitario??'';});}
  $('#editor').showModal();
  return true;
}
$('#record-form').addEventListener('submit',async event=>{
  event.preventDefault();
  if(photoBusy){$('#form-error').textContent='Espera a que termine la preparación de las fotografías.';return;}
  const table=current;const data=Object.fromEntries(new FormData(event.target));
  metadata[table].fields.filter(field=>['ref','integer'].includes(field.kind)).forEach(field=>{if(data[field.name]!=='')data[field.name]=Number(data[field.name]);});
  if(editing)data.__version=editing.__version;
  $('#save-record').disabled=true;$('#cancel-editor').disabled=true;$('#close-editor').disabled=true;$('#form-error').textContent='';
  try {
    const payload={id:editing?.[metadata[table].pk]??null,data};
    if(table==='incidencia'&&!editing&&reportPhotos.length)payload.evidencias=reportPhotos.map(({nombre,contenido})=>({nombre,contenido}));
    const result=await api('/api/records/'+table,payload);
    resetReportPhotos();
    if(qrReportActive && table==='incidencia' && !editing)finishQrReport();
    $('#editor').close();
    if(table==='incidencia' && !editing){
      showReportReceipt(result.id,data);
      notify(`¡Listo! Tu reporte ${reportReceipt.code} quedó registrado.`);
    }else notify(`¡Listo! Los cambios del registro #${result.id} se guardaron correctamente.`);
    if(table==='usuario'&&editing?.id_usuario===user.id_usuario){leave();$('#login-error').textContent='Tu cuenta cambió. Inicia sesión nuevamente.';return;}
    lookups=await api('/api/lookups'); await loadRows();
  }catch(error){$('#form-error').textContent=error.message;if(!$('#editor').open&&user)notify(error.message,true);}
  finally{$('#save-record').disabled=false;$('#cancel-editor').disabled=false;$('#close-editor').disabled=false;}
});

function showReportReceipt(id,data) {
  const asset=lookups.activo.find(item=>Number(item.id)===Number(data.id_activo));
  reportReceipt={id,code:'INC-'+String(id).padStart(6,'0'),
    equipo:asset?.label || 'Equipo #'+data.id_activo,
    descripcion:data.descripcion,prioridad:data.prioridad,estado:data.estado||'REPORTADA'};
  $('#receipt-code').textContent=reportReceipt.code;
  $('#receipt-id').textContent='Incidencia N.º '+id;
  $('#receipt-message').textContent=reportReceipt.estado==='REPORTADA'
    ? 'Gracias por avisarnos. Tu reporte quedó registrado y está listo para revisión.'
    : 'Gracias por avisarnos. Tu reporte quedó registrado correctamente.';
  $('#receipt-details').innerHTML=[['Equipo',reportReceipt.equipo],['Prioridad',reportReceipt.prioridad],['Estado del reporte',reportReceipt.estado],['Descripción',reportReceipt.descripcion]].map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join('');
  $('#report-ticket').showModal();
}
function receiptText() {
  if(!reportReceipt)return '';
  const receipt=reportReceipt;
  return ['ANDINA MANTENCIÓN','COMPROBANTE DE REPORTE','',
    'Código de registro: '+receipt.code,'Incidencia Oracle: '+receipt.id,
    'Equipo: '+receipt.equipo,'Prioridad: '+receipt.prioridad,
    'Estado del reporte: '+receipt.estado,'','Descripción:',receipt.descripcion,'',
    'Guarda este código para identificar tu reporte.',
    'https://andina-mantencion.onrender.com/'].join('\n');
}
$('#download-ticket').addEventListener('click',()=>{
  if(!reportReceipt)return;
  const blob=new Blob(['\ufeff'+receiptText()],{type:'text/plain;charset=utf-8'});
  const url=URL.createObjectURL(blob);
  const link=document.createElement('a');link.href=url;link.download=reportReceipt.code+'.txt';
  document.body.appendChild(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
});
function closeReportTicket() {$('#report-ticket').close();reportReceipt=null;}
['#close-ticket','#done-ticket'].forEach(selector=>$(selector).addEventListener('click',closeReportTicket));
$('#report-ticket').addEventListener('cancel',()=>{reportReceipt=null;});
$('#editor').addEventListener('cancel',event=>{if($('#save-record').disabled)event.preventDefault();else{resetReportPhotos();if(qrReportActive)finishQrReport();}});
['#close-editor','#cancel-editor'].forEach(selector=>$(selector).addEventListener('click',()=>{if(qrReportActive)finishQrReport();resetReportPhotos();$('#editor').close();}));
$('#close-detail').addEventListener('click',()=>$('#detail').close());
$('#change-password').addEventListener('click',()=>{$('#password-form').reset();$('#password-error').textContent='';$('#password-dialog').showModal();});
$('#cancel-password').addEventListener('click',()=>$('#password-dialog').close());
$('#password-form').addEventListener('submit',async event=>{
 event.preventDefault();$('#password-error').textContent='';
 if($('#new-password').value!==$('#confirm-password').value){$('#password-error').textContent='Las contraseñas nuevas no coinciden.';return;}
 $('#save-password').disabled=true;
 try{await api('/api/password',{current:$('#current-password').value,password:$('#new-password').value});$('#password-form').reset();leave();$('#login-error').textContent='Contraseña actualizada. Inicia sesión con tu nueva clave.';}
 catch(error){$('#password-error').textContent=error.message;}
 finally{$('#save-password').disabled=false;}
});
async function start(){
 updateLoginIntent();
 if(pendingReport)$('#server-hint').textContent='Inicia sesión con tu cuenta para reportar la falla del activo indicado por el QR.';
 if(location.protocol==='file:'){$('#login-error').textContent='Esta versión se abre desde la dirección web publicada; no desde un archivo local.';$('#login-submit').disabled=true;return;}
 try{await enter(await api('/api/me'));}catch(error){leave();if(!error.message.includes('Inicia sesión'))$('#login-error').textContent=error.message;}
}
setInterval(async()=>{if(!user)return;try{await api('/api/me');if(user)$('#connection-status').textContent='● Oracle conectado';}catch(error){if(user)$('#connection-status').textContent='● Conexión sin confirmar';}},30000);
start();


$('#copy-ticket')?.addEventListener('click',async()=>{if(reportReceipt){try{await navigator.clipboard.writeText(reportReceipt.code);notify('Código de reporte copiado.');}catch(_){notify('Selecciona y copia el código mostrado.',true);}}});
