'use strict';
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
let user = null, csrf = '', metadata = {}, lookups = {}, current = 'dashboard', rows = [], page = 1, total = 0;
let editing = null, generation = 0, listGeneration = 0, searchTimer;
let pendingReport = new URLSearchParams(location.search || '').get('reportar');
let qrReportActive = false;
const names = {id_usuario:'Reportado / registrado por',fecha_reporte:'Fecha de reporte',fecha_creacion:'Fecha de creación',fecha_consumo:'Fecha de consumo',id_orden:'Orden',estado_anterior:'Estado anterior',estado_nuevo:'Estado nuevo',fecha_cambio:'Fecha del cambio',observaciones:'Observaciones'};
const relationNames = {id_usuario:'usuario',id_orden:'orden_trabajo'};
const menuOrder = ['activo','ubicacion','incidencia','orden_trabajo','intervencion','repuesto','consumo_repuesto','mantenimiento_preventivo','historial_estado','usuario','rol'];

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
  qrReportActive=false;
  user=null; csrf=''; metadata={}; lookups={}; rows=[]; generation++; listGeneration++;
  document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());
  $('#app').hidden=true; $('#login').hidden=false; $('#content').replaceChildren(); $('#navigation').replaceChildren();
  $('#password').value=''; $('#password').type='password'; $('#toggle-password').textContent='Mostrar'; $('#toggle-password').setAttribute('aria-pressed','false');
  $('#email').focus();
}
async function enter(result) {
  user=result.user; csrf=result.csrf;
  [metadata,lookups]=await Promise.all([api('/api/meta'),api('/api/lookups')]);
  $('#profile-name').textContent=`${user.nombre} ${user.apellido}`;
  $('#profile-role').textContent=user.rol; $('#avatar').textContent=(user.nombre[0]||'')+(user.apellido[0]||'');
  $('#navigation').innerHTML=(metadata.incidencia?.writable?'<button id="nav-report-failure" class="report-nav"><span aria-hidden="true">＋</span> REPORTAR FALLA</button>':'')+'<button class="nav-item" data-view="dashboard">▦ <span>Panel principal</span></button>'+menuOrder.filter(table=>metadata[table]).map(table=>`<button class="nav-item" data-view="${table}">◇ <span>${esc(metadata[table].title)}</span></button>`).join('');
  $('#nav-report-failure')?.addEventListener('click',reportFailure);
  $('#navigation').querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>render(button.dataset.view)));
  $('#login').hidden=true; $('#app').hidden=false; $('#message').hidden=true;
  $('#connection-status').textContent='● Oracle conectado';
  await render('dashboard');
  await continueQrReport();
}

function finishQrReport() {
  pendingReport=null;qrReportActive=false;
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
  await render('incidencia');
  if(!user || current!=='incidencia')return;
  const opened=await openEditor(null,{id_activo:asset.id,estado:'REPORTADA'});
  if(opened) {
    qrReportActive=true;
    $('#field-id_activo').value=String(asset.id);
    $('#editor-note').textContent=`Activo del QR: ${asset.codigo_activo} · ${asset.label}. Describe la falla y revisa la prioridad antes de guardar.`;
    $('#field-descripcion').focus();
  }
}
async function reportFailure(event) {
  if(!user)return;
  if(!metadata.incidencia?.writable){notify('Tu cuenta no tiene permiso para reportar incidencias.',true);return;}
  const trigger=event?.currentTarget;
  if(trigger)trigger.disabled=true;
  try {
    if(pendingReport){await continueQrReport();return;}
    await render('incidencia');
    if(!user || current!=='incidencia' || !$('#new-record'))return;
    const opened=await openEditor(null,{estado:'REPORTADA'});
    if(opened){
      $('#editor-title').textContent='Reportar falla';
      $('#editor-note').textContent='Selecciona el activo, describe lo que ocurre y revisa la prioridad. El reporte se enviará al pulsar Guardar en Oracle.';
      $('#field-id_activo').focus();
    }
  }catch(error){if(user)notify(error.message,true);}
  finally{if(trigger)trigger.disabled=false;}
}
function reportShortcut() {
  if(!metadata.incidencia?.writable)return '';
  return '<section class="report-hero" aria-labelledby="report-heading"><div class="report-symbol" aria-hidden="true">!</div><div class="report-copy"><span class="report-eyebrow">REPORTE DE FALLAS</span><h2 id="report-heading">¿Detectaste una falla?</h2><p>Selecciona el activo y cuéntanos qué ocurre.</p></div><button id="dashboard-report-failure" class="report-action">REPORTAR FALLA <span aria-hidden="true">→</span></button></section>';
}
$('#login-form').addEventListener('submit',async event=>{
  event.preventDefault(); $('#login-submit').disabled=true; $('#login-error').textContent='';
  try { const result=await api('/api/login',{correo:$('#email').value.trim(),password:$('#password').value}); $('#password').value=''; await enter(result); }
  catch(error) { leave(); $('#login-error').textContent=error.message; }
  finally { $('#login-submit').disabled=false; }
});
$('#toggle-password').addEventListener('click',()=>{const show=$('#password').type==='password';$('#password').type=show?'text':'password';$('#toggle-password').textContent=show?'Ocultar':'Mostrar';$('#toggle-password').setAttribute('aria-pressed',String(show));});
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
      $('#content').innerHTML=heading(table,'Datos actuales de tu base de datos.')+reportShortcut()+`<section class="stats">${Object.entries(dashboard.stats).map(([label,value])=>`<article class="card stat"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>Consulta real en Oracle</small></article>`).join('')}</section><section class="card"><div class="card-header"><div><h3>Últimas incidencias</h3><p>Los cinco reportes más recientes</p></div><button class="text-button" id="open-incidents">Ver incidencias →</button></div><div class="table-scroll"><table><thead><tr><th>ID / ACTIVO</th><th>DESCRIPCIÓN</th><th>PRIORIDAD</th><th>ESTADO</th></tr></thead><tbody>${dashboard.incidencias.map(row=>`<tr><td>#${esc(row.id_incidencia)} · ${esc(row.codigo_activo)}</td><td class="wrap">${esc(row.descripcion)}</td><td>${esc(row.prioridad)}</td><td>${esc(row.estado)}</td></tr>`).join('')}</tbody></table></div>${dashboard.incidencias.length?'':'<p class="empty">Todavía no hay incidencias registradas.</p>'}</section><div class="banner dashboard-note">Estás trabajando con datos reales. Los formularios guardan cambios en Oracle y el historial de órdenes se genera automáticamente.</div>`;
      $('#dashboard-report-failure')?.addEventListener('click',reportFailure);
      $('#open-incidents').addEventListener('click',()=>render('incidencia'));
    } else {
      const spec=metadata[table];
      const states=spec.fields.find(field=>field.name==='estado')?.options;
      $('#content').innerHTML=heading(table,table==='historial_estado'?'Trazabilidad automática de los estados de las órdenes.':'Consulta, busca y gestiona los registros de este módulo.')+`<div class="filters"><div><label for="search">Buscar por ID o texto</label><input id="search" type="search" placeholder="Escribe para buscar…" maxlength="150"></div>${states?`<div><label for="state-filter">Estado</label><select id="state-filter"><option value="">Todos</option>${states.map(state=>`<option>${state}</option>`).join('')}</select></div>`:''}<button id="clear" class="secondary">Limpiar</button>${spec.writable?'<button id="new-record" class="primary">+ Nuevo registro</button>':''}</div><section class="card"><div id="records" aria-live="polite"></div><div class="pagination"><span id="page-info"></span><div><button id="previous" class="secondary">← Anterior</button><button id="next" class="secondary">Siguiente →</button></div></div></section><p class="muted small">${table==='consumo_repuesto'?'Al guardar se descuenta stock. Al corregir un consumo se ajusta la diferencia en la misma transacción.':table==='usuario'?'Solo administradores. Una contraseña vacía conserva la actual al editar. Guardar cierra las sesiones de ese usuario.':table==='orden_trabajo'?'Flujo: PENDIENTE → ASIGNADA → EN_PROCESO → FINALIZADA. También puedes cancelar una orden no finalizada.':'Los registros se conservan para mantener sus relaciones. Usa los estados disponibles para desactivar o cancelar.'}</p>`;
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
    container.innerHTML=rows.length?`<div class="table-scroll"><table><thead><tr>${cols.map(col=>`<th>${esc(fieldLabel(table,col))}</th>`).join('')}<th>Acciones</th></tr></thead><tbody>${rows.map((row,index)=>`<tr>${cols.map(col=>`<td class="wrap" title="${esc(display(table,col,row[col]))}">${esc(display(table,col,row[col]))}</td>`).join('')}<td><div class="row-actions"><button class="text-button" data-detail="${index}">Detalle</button>${canEdit(table,row)?`<button class="text-button" data-edit="${index}">Editar</button>`:''}</div></td></tr>`).join('')}</tbody></table></div>`:'<p class="empty">No hay registros que coincidan con estos filtros.</p>';
    container.querySelectorAll('[data-detail]').forEach(button=>button.addEventListener('click',()=>openDetail(rows[Number(button.dataset.detail)])));
    container.querySelectorAll('[data-edit]').forEach(button=>button.addEventListener('click',()=>openEditor(rows[Number(button.dataset.edit)])));
    $('#page-info').textContent=`${total} registros · Página ${page} de ${Math.max(1,Math.ceil(total/25))}`;
    $('#previous').disabled=page<=1;$('#next').disabled=page*25>=total;
  }catch(error){if(request===listGeneration && user){container.innerHTML='<p class="empty">No se pudieron cargar los registros.</p>';notify(error.message,true);}}
}
function canEdit(table,row) {
  if(!metadata[table].writable)return false;
  if(['OPERADOR','TECNICO'].includes(user.rol) && table==='incidencia')return row.id_usuario===user.id_usuario && row.estado==='REPORTADA';
  if(user.rol==='TECNICO') {
    if(table==='intervencion')return row.id_usuario===user.id_usuario && lookups.orden_trabajo.some(order=>order.id===row.id_orden&&order.id_usuario_asignado===user.id_usuario&&order.estado==='EN_PROCESO');
    if(table==='consumo_repuesto'){const intervention=lookups.intervencion.find(item=>item.id===row.id_intervencion);return intervention?.id_usuario===user.id_usuario && lookups.orden_trabajo.some(order=>order.id===intervention.id_orden&&order.id_usuario_asignado===user.id_usuario&&order.estado==='EN_PROCESO');}
  }
  return true;
}
function openDetail(row) {
  const spec=metadata[current];$('#detail-title').textContent=`${spec.title} · #${row[spec.pk]}`;
  $('#detail-content').innerHTML=spec.columns.map(col=>`<dt>${esc(fieldLabel(current,col))}</dt><dd>${esc(display(current,col,row[col]))}</dd>`).join('');
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
  const table=current;
  try{lookups=await api('/api/lookups');}catch(error){notify(error.message,true);return;}
  if(current!==table || !user)return;
  editing=row; const spec=metadata[table];$('#record-form').reset();$('#form-error').textContent='';
  $('#editor-title').textContent=`${row?'Editar':'Nuevo registro'} · ${spec.title}`;
  $('#editor-note').textContent=table==='consumo_repuesto'?'El stock se ajustará al guardar. No se permite stock negativo.':table==='orden_trabajo'?'Cada cambio de estado se registra en el historial. Completa las fechas al iniciar o finalizar.':'Los cambios se guardan en Oracle. Los campos con * son obligatorios.';
  $('#fields').innerHTML=spec.fields.map(field=>{
    const name=field.name,id='field-'+name;let value=row?.[name]??preset[name]??field.default??'';
    if(field.kind==='date')value=String(value).slice(0,10);
    if(field.kind==='datetime')value=String(value).slice(0,19);
    const required=field.required?'required':'';let control;
    if(field.kind==='ref')control=`<select id="${id}" name="${name}" ${required}><option value="">Selecciona…</option>${optionsFor(field,row).map(item=>`<option value="${item.id}" ${Number(value)===Number(item.id)?'selected':''}>#${item.id} · ${esc(item.label)}${item.stock_actual===undefined?'':` · stock ${esc(item.stock_actual)}`}</option>`).join('')}</select>`;
    else if(field.kind==='select') {
      let choices=field.options;
      if(table==='incidencia'&&['OPERADOR','TECNICO'].includes(user.rol))choices=['REPORTADA'];
      if(table==='orden_trabajo') {const next={PENDIENTE:['ASIGNADA','CANCELADA'],ASIGNADA:['PENDIENTE','EN_PROCESO','CANCELADA'],EN_PROCESO:['FINALIZADA','CANCELADA'],FINALIZADA:[],CANCELADA:[]};choices=row?[row.estado,...(next[row.estado]||[])]:['PENDIENTE','ASIGNADA'];}
      control=`<select id="${id}" name="${name}" ${required}>${choices.map(option=>`<option ${value===option?'selected':''}>${esc(option)}</option>`).join('')}</select>`;
    } else if(field.kind==='text'&&field.length>=500)control=`<textarea id="${id}" name="${name}" maxlength="${field.length}" rows="3" ${required}>${esc(value)}</textarea>`;
    else {const type={integer:'number',money:'number',datetime:'datetime-local',date:'date',email:'email'}[field.kind]||'text';control=`<input id="${id}" name="${name}" type="${type}" value="${esc(value)}" ${required} ${field.length?`maxlength="${field.length}"`:''} ${field.minimum===undefined?'':`min="${field.minimum}" max="${field.maximum}"`} ${['money','integer','datetime'].includes(field.kind)?`step="${field.kind==='money'?'.01':'1'}"`:''}>`;}
    return `<div class="${field.length>=500?'span-two':''}"><label for="${id}">${esc(field.label)}${field.required?' *':''}</label>${control}</div>`;
  }).join('')+(table==='usuario'?`<div class="span-two"><label for="field-password">${row?'Nueva contraseña (vacía para conservar)':'Contraseña inicial *'}</label><input id="field-password" name="password" type="password" autocomplete="new-password" minlength="12" maxlength="128" ${row?'':'required'}><small>Entre 12 y 128 caracteres. El servidor guarda solo su hash.</small></div>`:'');
  if(table==='consumo_repuesto' && !row){$('#field-id_repuesto').addEventListener('change',()=>{const item=lookups.repuesto.find(item=>String(item.id)===$('#field-id_repuesto').value);$('#field-precio_unitario').value=item?.precio_unitario??'';});}
  $('#editor').showModal();
  return true;
}
$('#record-form').addEventListener('submit',async event=>{
  event.preventDefault();const table=current;const data=Object.fromEntries(new FormData(event.target));
  metadata[table].fields.filter(field=>['ref','integer'].includes(field.kind)).forEach(field=>{if(data[field.name]!=='')data[field.name]=Number(data[field.name]);});
  if(editing)data.__version=editing.__version;
  $('#save-record').disabled=true;$('#cancel-editor').disabled=true;$('#close-editor').disabled=true;$('#form-error').textContent='';
  try {
    const result=await api('/api/records/'+table,{id:editing?.[metadata[table].pk]??null,data});
    if(qrReportActive && table==='incidencia' && !editing)finishQrReport();
    $('#editor').close(); notify(`Registro #${result.id} guardado correctamente en Oracle.`);
    if(table==='usuario'&&editing?.id_usuario===user.id_usuario){leave();$('#login-error').textContent='Tu cuenta cambió. Inicia sesión nuevamente.';return;}
    lookups=await api('/api/lookups'); await loadRows();
  }catch(error){$('#form-error').textContent=error.message;if(!$('#editor').open&&user)notify(error.message,true);}
  finally{$('#save-record').disabled=false;$('#cancel-editor').disabled=false;$('#close-editor').disabled=false;}
});
$('#editor').addEventListener('cancel',event=>{if($('#save-record').disabled)event.preventDefault();else if(qrReportActive)finishQrReport();});
['#close-editor','#cancel-editor'].forEach(selector=>$(selector).addEventListener('click',()=>{if(qrReportActive)finishQrReport();$('#editor').close();}));
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
 if(pendingReport)$('#server-hint').textContent='Inicia sesión con tu cuenta para reportar la falla del activo indicado por el QR.';
 if(location.protocol==='file:'){$('#login-error').textContent='Esta versión se abre desde la dirección web publicada; no desde un archivo local.';$('#login-submit').disabled=true;return;}
 try{await enter(await api('/api/me'));}catch(error){leave();if(!error.message.includes('Inicia sesión'))$('#login-error').textContent=error.message;}
}
setInterval(async()=>{if(!user)return;try{await api('/api/me');if(user)$('#connection-status').textContent='● Oracle conectado';}catch(error){if(user)$('#connection-status').textContent='● Conexión sin confirmar';}},30000);
start();
