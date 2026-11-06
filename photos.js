'use strict';
let reportPhotos=[],photoGeneration=0,photoBusy=false;
function resetReportPhotos(){
 photoGeneration++;photoBusy=false;
 for(const photo of reportPhotos)URL.revokeObjectURL(photo.preview);
 reportPhotos=[];
}
function stitchEvidencePicker(){
 if(!metadata.incidencia?.evidencia_habilitada)return `<div class="report-evidence">${stitchSymbol('add_a_photo')}El almacenamiento de fotografías está pendiente de activación.<br><small>Puedes enviar el reporte sin fotografías.</small></div>`;
 return `<div class="report-evidence">${stitchSymbol('add_a_photo')}Adjunta fotografías del equipo o de la falla.<br><small>Hasta 3 imágenes JPG, PNG o WebP. Se ajustan automáticamente para enviarlas.</small><label class="photo-pick" for="report-photos">Elegir fotografías / cámara</label><input type="file" id="report-photos" accept="image/jpeg,image/png,image/webp" multiple hidden><p id="photo-error" class="error" role="alert"></p></div><div id="photo-list" class="photo-list"></div>`;
}
function refreshPhotoList(){
 const list=$('#photo-list');if(!list)return;
 list.innerHTML=reportPhotos.map((p,i)=>`<article><img src="${esc(p.preview)}" alt="Fotografía ${i+1}: ${esc(p.nombre)}"><div><span>${esc(p.nombre)}</span><button type="button" data-remove-photo="${i}" aria-label="Quitar fotografía ${i+1}">Quitar</button></div></article>`).join('');
}
async function preparePhoto(file){
 if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>10_000_000)throw new Error('Usa imágenes JPG, PNG o WebP de hasta 10 MB.');
 let bitmap;
 try{
  bitmap=await createImageBitmap(file,{imageOrientation:'from-image'});
  const scale=Math.min(1,1600/Math.max(bitmap.width,bitmap.height));
  const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));
  const context=canvas.getContext('2d');context.fillStyle='#ffffff';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(bitmap,0,0,canvas.width,canvas.height);
  const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.82));
  if(!blob||blob.size>2_000_000)throw new Error('La imagen no pudo ajustarse a 2 MB. Elige otra fotografía.');
  const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('No se pudo leer la fotografía.'));reader.readAsDataURL(blob);});
  return {nombre:file.name.slice(0,100),contenido:encoded,preview:URL.createObjectURL(blob)};
 }finally{bitmap?.close();}
}
function initializePhotoPicker(){
 const input=$('#report-photos');if(!input)return;
 input.addEventListener('change',async()=>{
  const generation=photoGeneration,files=Array.from(input.files||[]);
  $('#photo-error').textContent='';
  if(files.length+reportPhotos.length>3){$('#photo-error').textContent='Puedes adjuntar hasta 3 fotografías.';input.value='';return;}
  photoBusy=true;$('#save-record').disabled=true;
  try{
   for(const file of files){
    const photo=await preparePhoto(file);
    if(generation!==photoGeneration){URL.revokeObjectURL(photo.preview);return;}
    reportPhotos.push(photo);refreshPhotoList();
   }
  }catch(error){if(generation===photoGeneration)$('#photo-error').textContent=error.message||'No se pudo leer la imagen. Selecciona otra fotografía.';}
  finally{if(generation===photoGeneration){photoBusy=false;$('#save-record').disabled=false;input.value='';}}
 });
 $('#photo-list').addEventListener('click',event=>{
  const button=event.target.closest('[data-remove-photo]');if(!button||photoBusy)return;
  const index=Number(button.dataset.removePhoto);if(!Number.isInteger(index)||!reportPhotos[index])return;
  URL.revokeObjectURL(reportPhotos[index].preview);reportPhotos.splice(index,1);refreshPhotoList();
 });
}
async function loadIncidentPhotos(id){
 const gallery=$('#incident-photos');if(!gallery)return;
 try{
  const result=await api(`/api/incidencias/${id}/evidencias`);
  if($('#incident-photos')!==gallery)return;
  gallery.innerHTML=result.evidencias.length?`<h3>Evidencia fotográfica</h3><div class="incident-photo-grid">`+result.evidencias.map(p=>`<a href="/api/evidencias/${p.id_evidencia}" target="_blank" rel="noopener"><img loading="lazy" src="/api/evidencias/${p.id_evidencia}" alt="${esc(p.nombre)}"><span>${esc(p.nombre)}</span></a>`).join('')+'</div>':'<p class="muted">Sin fotografías adjuntas.</p>';
 }catch(error){if($('#incident-photos')===gallery)gallery.textContent=error.message;}
}
