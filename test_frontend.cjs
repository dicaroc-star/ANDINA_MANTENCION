// Pruebas de lógica de la interfaz con DOM simulado; no reemplazan QA visual.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),{execFileSync}=require('child_process');
const metadata=JSON.parse(execFileSync('python',['-c',"import json; from service import Service; print(json.dumps(Service(None).metadata('ADMINISTRADOR')))"],{encoding:'utf8'}));
const source=fs.readFileSync('app.js','utf8');
const elements=new Map();
class Element {
 constructor(id=''){this.id=id;this.value='';this.hidden=false;this.disabled=false;this.dataset={};this.children=[];this.listeners={};this.open=false;this.textContent='';this.classList={toggle(){}};this.type='password';}
 set innerHTML(html){for(const child of this.children)if(child.id)elements.delete('#'+child.id);this.children=[];this.html=html;
  for(const match of html.matchAll(/<([a-z-]+)\b([^>]*)>/g)){const attrs=match[2];const id=attrs.match(/\bid="([^"]+)"/)?.[1];const view=attrs.match(/\bdata-view="([^"]+)"/)?.[1];if(id||view){const child=new Element(id||'');if(view)child.dataset.view=view;child.value=attrs.match(/\bvalue="([^"]*)"/)?.[1]||'';this.children.push(child);if(id)elements.set('#'+id,child);}}
 }
 get innerHTML(){return this.html||'';}
 querySelectorAll(selector){if(selector==='[data-view]')return this.children.filter(child=>child.dataset.view);return [];}
 addEventListener(event,fn){this.listeners[event]=fn;}
 setAttribute(){} removeAttribute(){} focus(){} reset(){} replaceChildren(){this.innerHTML='';} showModal(){this.open=true;}close(){this.open=false;}
}
for(const match of fs.readFileSync('index.html','utf8').matchAll(/id="([^"]+)"/g))elements.set('#'+match[1],new Element(match[1]));
const document={querySelector:selector=>elements.get(selector)||null,querySelectorAll:selector=>selector==='dialog[open]'?[...elements.values()].filter(el=>el.open):selector==='[data-view]'?elements.get('#navigation').querySelectorAll(selector):[]};
const lookups={rol:[{id:1,label:'ADMINISTRADOR'}],ubicacion:[{id:1,label:'PRUEBA'}],activo:[{id:1,label:'<img src=x onerror=alert(1)>',estado:'OPERATIVO'}],usuario:[{id:1,label:'CUENTA TEST',estado:'ACTIVO'}],incidencia:[{id:1,label:'PRUEBA',estado:'REPORTADA'}],orden_trabajo:[{id:1,label:'TEST',estado:'EN_PROCESO',id_usuario_asignado:1}],intervencion:[{id:1,label:'TEST',id_orden:1,id_usuario:1}],repuesto:[{id:1,label:'TEST',estado:'ACTIVO',precio_unitario:12,stock_actual:5}]};
const records=Object.fromEntries(Object.entries(metadata).map(([table,spec])=>[table,[Object.fromEntries([[spec.pk,1],['__version','test'],...spec.fields.map(field=>[field.name,field.kind==='ref'?1:field.options?.[0]??field.default??(field.kind==='date'?'2026-11-01':field.kind==='datetime'?'2026-11-01T12:00:00':field.kind==='integer'||field.kind==='money'?1:'<script>alert(1)</script>')]),...((spec.readonly||[]).map(name=>[name,name.startsWith('fecha')?'2026-11-01T12:00:00':name.startsWith('id')?1:'TEST']))])]]));
const calls=[];let rejectSave=false;
async function fetch(path,options){calls.push({path,options});let result,status=200;
 if(path==='/api/me'){result={error:'Inicia sesión para continuar.'};status=401;}
 else if(path==='/api/meta')result=metadata;
 else if(path==='/api/lookups')result=lookups;
 else if(path==='/api/dashboard')result={stats:{'Activos operativos':1},incidencias:[]};
 else if(path.startsWith('/api/records/')){const table=path.split('/')[3].split('?')[0];if(options.method==='POST'){if(rejectSave){status=409;result={error:'Stock insuficiente'};}else result={id:1};}else result={rows:records[table],total:1,page:1};}
 else if(path==='/api/logout')result={ok:true};
 else throw new Error('Ruta inesperada: '+path);
 return {ok:status===200,status,json:async()=>result};
}
const context=vm.createContext({document,fetch,location:{protocol:'http:'},URLSearchParams,setInterval(){},setTimeout,clearTimeout,FormData:class{constructor(form){return Object.entries(form.formData||{});}}});
vm.runInContext(source,context);
const run=code=>vm.runInContext(code,context);
(async()=>{
 await new Promise(resolve=>setImmediate(resolve));
 context.account={user:{id_usuario:1,nombre:'CUENTA',apellido:'TEST',rol:'ADMINISTRADOR'},csrf:'token-test'};
 await run('enter(account)');assert.equal(elements.get('#app').hidden,false);
 for(const table of Object.keys(metadata)){
  await run(`render('${table}')`);assert.match(elements.get('#content').innerHTML,/Buscar/);
  assert.ok(!elements.get('#records').innerHTML.includes('<script>'));
  await run('openDetail(rows[0])');assert.ok(elements.get('#detail').open);assert.ok(!elements.get('#detail-content').innerHTML.includes('<script>'));
  elements.get('#detail').close();
  if(metadata[table].writable){await run('openEditor(null)');for(const field of metadata[table].fields)assert.ok(elements.has('#field-'+field.name),table+' '+field.name);elements.get('#editor').close();}
 }
 await run("render('incidencia')");await run('openEditor(null)');
 elements.get('#record-form').formData={id_activo:'1',descripcion:'PRUEBA LOCAL',prioridad:'ALTA',estado:'REPORTADA'};
 await elements.get('#record-form').listeners.submit({preventDefault(){},target:elements.get('#record-form')});
 const saved=calls.filter(call=>call.path==='/api/records/incidencia'&&call.options.method==='POST').pop();
 assert.equal(JSON.parse(saved.options.body).data.id_activo,1);assert.equal(saved.options.headers['X-CSRF-Token'],'token-test');
 await run("render('consumo_repuesto')");await run('openEditor(null)');rejectSave=true;
 elements.get('#record-form').formData={id_intervencion:'1',id_repuesto:'1',cantidad:'10',precio_unitario:'12'};
 await elements.get('#record-form').listeners.submit({preventDefault(){},target:elements.get('#record-form')});
 assert.equal(elements.get('#form-error').textContent,'Stock insuficiente');assert.ok(elements.get('#editor').open);
 await elements.get('#logout').listeners.click();assert.equal(elements.get('#app').hidden,true);
 console.log('OK: 11 módulos, formularios, detalle, escape de HTML, guardado con CSRF, error de stock y cierre de sesión. DOM simulado; sin revisión visual.');
})().catch(error=>{console.error(error);process.exitCode=1;});
