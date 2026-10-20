/* Preview local evidence without executing document contents or sending files elsewhere. */
"use strict";
const richAttachmentPreview=(()=>{
  let revision=0,active=null,boundDialog=null;

  function clearActive(){
    ++revision;
    if(!active)return;
    active.controller?.abort();
    for(const media of active.media){
      try{media.pause();media.removeAttribute('src');media.load();}catch{}
    }
    for(const frame of active.frames)frame.removeAttribute('src');
    active=null;
  }

  function bind(dialog){
    if(boundDialog===dialog)return;
    boundDialog=dialog;
    dialog.addEventListener('close',()=>{if(!dialog.open)clearActive();});
    dialog.addEventListener('cancel',()=>clearActive());
    dialog.addEventListener('click',event=>{
      if(event.target!==dialog)return;
      const bounds=dialog.getBoundingClientRect();
      if(event.clientX<bounds.left||event.clientX>bounds.right||event.clientY<bounds.top||event.clientY>bounds.bottom)dialog.close();
    });
  }

  function kindOf(attachment){
    const mime=String(attachment.mime||'').toLowerCase().split(';')[0].trim();
    const extension=String(attachment.name||'').toLowerCase().split('.').pop();
    if(mime.startsWith('image/')||['png','jpg','jpeg','gif','webp','bmp','ico','avif','svg','tif','tiff','heic','heif'].includes(extension))return 'image';
    if(mime.startsWith('video/')||['mp4','mov','mkv','webm','avi','m4v','mpeg','mpg','3gp'].includes(extension))return 'video';
    if(mime.startsWith('audio/')||['mp3','wav','ogg','oga','m4a','aac','flac','amr','aiff','opus','wma'].includes(extension))return 'audio';
    if(mime==='application/pdf'||extension==='pdf')return 'pdf';
    return '';
  }

  function notice(body,message,warning=false){
    if(!message)return;
    const copy=node('p','attachment-preview-notice'+(warning?' warning':''),String(message));
    body.append(copy);
    return copy;
  }

  function status(body,title,description){
    const panel=node('div','attachment-preview-status');
    panel.setAttribute('role','status');
    panel.append(node('strong','',title));
    if(description)panel.append(node('p','',description));
    body.append(panel);
  }

  function table(rows,headers){
    const wrap=node('div','attachment-preview-table-scroll');
    wrap.tabIndex=0;
    const grid=node('table','attachment-preview-table'),head=node('thead'),body=node('tbody');
    const heading=node('tr');
    headers.forEach(label=>{const cell=node('th','',String(label??''));cell.scope='col';heading.append(cell);});
    head.append(heading);
    rows.forEach(row=>{
      const line=node('tr');
      for(let index=0;index<headers.length;++index)line.append(node('td','',String(row[index]??'')));
      body.append(line);
    });
    grid.append(head,body);wrap.append(grid);
    return wrap;
  }

  function renderTable(body,payload){
    const sheets=Array.isArray(payload.sheets)?payload.sheets.filter(sheet=>sheet&&Array.isArray(sheet.rows)):[];
    if(!sheets.length){status(body,'这个表格没有可预览的内容。');return;}
    const controls=node('div','attachment-preview-sheet-controls');
    const label=node('label','attachment-preview-sheet-label');
    const select=node('select');select.setAttribute('aria-label','选择预览工作表');
    sheets.forEach((sheet,index)=>{const option=node('option','',String(sheet.name||'工作表 '+(index+1)));option.value=String(index);select.append(option);});
    label.append(select);controls.append(label);
    if(sheets.length>1)body.append(controls);
    const slot=node('div','attachment-preview-table-slot');body.append(slot);
    function choose(){
      const sheet=sheets[Number(select.value)||0],rows=sheet.rows.filter(Array.isArray);
      slot.replaceChildren();
      if(!rows.length){status(slot,'这个工作表没有可预览的内容。');return;}
      const columns=rows.reduce((width,row)=>Math.max(width,row.length),0);
      if(!columns){status(slot,'这个工作表没有可预览的内容。');return;}
      const headings=Array.from({length:columns},(_,index)=>rows[0][index]??'');
      slot.append(table(rows.slice(1),headings));
      if(sheet.truncated&&!payload.truncated)notice(slot,'此工作表为部分预览，完整内容请在本机打开原文件查看。',true);
    }
    select.addEventListener('change',choose);choose();
  }

  function renderPayload(body,payload){
    if(!payload||typeof payload!=='object')throw new Error('本地工具没有返回有效预览，请重试。');
    if(payload.kind==='text'||payload.kind==='document'){
      if(typeof payload.text!=='string')throw new Error('这个文件没有可读取的预览内容。');
      const text=node('pre','attachment-preview-text',payload.text);
      text.tabIndex=0;body.append(text);
      if(!payload.text)notice(body,'这个文件没有可显示的文字。');
    }else if(payload.kind==='table')renderTable(body,payload);
    else if(payload.kind==='archive'){
      const entries=Array.isArray(payload.entries)?payload.entries:[];
      if(entries.length)body.append(table(entries.map(entry=>[
        String(entry.name??''),entry.directory?'文件夹':formatBytes(Number(entry.size)||0),
      ]),['压缩包内路径','大小']));
      else status(body,'这个压缩包没有可列出的文件。');
    }else status(body,'暂不支持直接预览此格式',String(payload.message||'请在原始文件夹中，用本机应用打开查看。'));
    if(payload.truncated)notice(body,'当前为部分预览，完整内容请在本机打开原文件查看。',true);
    const notes=[];
    if(payload.kind==='document')notes.push('这里只显示正文文字；原始排版、图片和批注请在本机打开原文件查看。');
    if(payload.kind==='archive')notes.push('仅列出压缩包内的文件，不会解压或打开其中的程序。');
    if(payload.notice)notes.push(String(payload.notice));
    if(notes.length){
      const details=node('details','attachment-preview-details');
      details.append(node('summary','','预览说明'),node('p','',notes.join('\n')));body.append(details);
    }
  }

  async function show(bug,attachment){
    const dialog=$('previewDialog'),content=$('previewContent');
    clearActive();bind(dialog);
    const session={id:revision,controller:null,media:[],frames:[]};active=session;
    const current=()=>active===session&&revision===session.id&&dialog.open;
    $('previewTitle').textContent=String(attachment.name||'附件预览');
    dialog.classList.add('attachment-preview-modal');content.classList.add('attachment-preview-content');
    const url=attachmentUrl(bug,attachment),kind=kindOf(attachment);
    dialog.setAttribute('data-preview-kind',kind||'document');
    const body=node('div','attachment-preview-body');content.replaceChildren(body);
    if(!dialog.open)dialog.showModal();

    if(['image','video','audio'].includes(kind)){
      const media=node(kind==='image'?'img':kind,'attachment-preview-'+kind);
      if(kind==='image')media.alt=String(attachment.name||'附件图片');
      else{
        media.controls=true;media.preload='metadata';
        if(kind==='video')media.playsInline=true;
        session.media.push(media);
      }
      const failure=node('p','attachment-preview-notice warning');failure.hidden=true;failure.setAttribute('role','status');
      media.addEventListener('error',()=>{
        if(!current())return;
        failure.textContent=kind==='image'?'浏览器无法显示这张图片，请在本机打开原文件查看。':'浏览器无法播放此文件，可能不支持它的编码。请在原始文件夹中用本机播放器打开。';failure.hidden=false;
      });
      body.classList.add('attachment-preview-media');body.append(media,failure);media.src=url;
      return;
    }
    if(kind==='pdf'){
      const frame=node('iframe','attachment-preview-pdf');frame.title=String(attachment.name||'PDF 附件预览');
      session.frames.push(frame);body.append(frame);frame.src=url;
      return;
    }
    session.controller=new AbortController();body.setAttribute('aria-busy','true');
    status(body,'正在读取附件…');
    try{
      const response=await fetch('/api/attachment-preview?bug_id='+encodeURIComponent(bug.id)+'&attachment_id='+encodeURIComponent(attachment.id),{cache:'no-store',signal:session.controller.signal});
      if(!current())return;
      let payload;try{payload=await response.json();}catch{throw new Error('预览没有加载成功，请重试或在本机打开原文件。');}
      if(!current())return;
      if(!response.ok||payload?.error)throw new Error(payload?.error||'预览没有加载成功，请在本机打开原文件查看。');
      body.replaceChildren();renderPayload(body,payload);
    }catch(error){
      if(!current()||error?.name==='AbortError')return;
      body.replaceChildren();status(body,'预览没有加载成功',error instanceof TypeError?'无法连接本地工具，请重试或在本机打开原文件。':errorMessage(error));
    }finally{if(current())body.setAttribute('aria-busy','false');}
  }
  return {show};
})();
function showRichAttachment(bug,attachment){return richAttachmentPreview.show(bug,attachment);}
