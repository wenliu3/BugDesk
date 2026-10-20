/* Exercise attachment previews with synthetic evidence and a deliberately HTML-hostile DOM. */
"use strict";
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};

function harness(){
  const elements=new Map(),requests=[];
  function create(tag){
    let id='',ownText='';
    const item={tagName:tag.toUpperCase(),children:[],listeners:{},attributes:{},value:'',open:false,hidden:false,pauseCount:0,loadCount:0,
      get textContent(){return ownText+this.children.map(child=>child.textContent).join('');},
      set textContent(value){ownText=String(value);this.children=[];},
      get innerHTML(){throw new Error('Attachment preview must never read HTML');},
      set innerHTML(value){throw new Error('Attachment preview must never render file contents as HTML');},
      get id(){return id;},set id(value){id=value;elements.set(value,this);},
      setAttribute(key,value){this.attributes[key]=String(value);},
      removeAttribute(key){delete this.attributes[key];if(key==='src')delete this.src;},
      addEventListener(type,listener){(this.listeners[type]||=[]).push(listener);},
      append(...children){this.children.push(...children);for(const child of children)child.parentElement=this;},
      prepend(...children){this.children.unshift(...children);for(const child of children)child.parentElement=this;},
      replaceChildren(...children){ownText='';this.children=[];this.append(...children);},
      showModal(){this.open=true;},
      close(){if(this.open){this.open=false;fire(this,'close');}},
      pause(){++this.pauseCount;},load(){++this.loadCount;},
      getBoundingClientRect(){return {left:10,right:300,top:10,bottom:300};}
    };
    item.classList={names:new Set(),add(...names){for(const name of names)this.names.add(name);},contains(name){return this.names.has(name);}};
    return item;
  }
  function fire(item,type,detail={}){
    if(typeof item==='string')item=elements.get(item);
    const event={target:item,defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},...detail};
    for(const listener of item.listeners[type]||[])listener(event);
    if(type==='cancel'&&!event.defaultPrevented)item.close();
    return event;
  }
  function all(root,tag){const result=[];for(const child of root.children){if(!tag||child.tagName===tag.toUpperCase())result.push(child);result.push(...all(child,tag));}return result;}
  const node=(tag,className='',content)=>{const item=create(tag);item.className=className;if(content!==undefined)item.textContent=content;return item;};
  const dialog=node('dialog');dialog.id='previewDialog';
  const title=node('h2');title.id='previewTitle';
  const content=node('div');content.id='previewContent';dialog.append(title,content);
  const context={console,AbortController,TypeError,Error,Promise,String,Number,Array,encodeURIComponent,
    $:id=>elements.get(id),node,icon:name=>node('span','icon',name),
    formatBytes:size=>size+' B',errorMessage:error=>error?.message||'操作失败',
    attachmentUrl:(bug,attachment)=>'/api/attachment?bug_id='+encodeURIComponent(bug.id)+'&attachment_id='+encodeURIComponent(attachment.id),
    fetch:(url,init)=>{const pending=deferred();requests.push({url,init,...pending});return pending.promise;}
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'..','web','attachment_preview.js'),'utf8'),context,{filename:'attachment_preview.js'});
  const show=(attachment={},bug={id:'bug-1'})=>context.showRichAttachment(bug,{id:'file-1',name:'log.txt',size:12,mime:'text/plain',...attachment});
  const reply=(index,payload,ok=true)=>requests[index].resolve({ok,json:async()=>payload});
  return {context,dialog,title,content,requests,show,reply,fire,all,
    text:()=>content.textContent,
    one:tag=>all(content,tag)[0],
    downloads:()=>all(content,'a').filter(link=>Object.hasOwn(link,'download')),
    has:className=>all(content).filter(item=>item.className===className)
  };
}

test('plain text stays inert and shows only content without metadata or download controls',async()=>{
  const h=harness(),hostile='<img src=x onerror="alert(1)"><script>bad()</script>';
  const pending=h.show({name:hostile+'.txt'});
  assert.equal(h.dialog.open,true);assert.match(h.text(),/正在读取附件/);
  h.reply(0,{kind:'text',text:hostile+'\nline 2',encoding:'UTF-8'});await pending;
  assert.equal(h.title.textContent,hostile+'.txt');assert.equal(h.one('pre').textContent,hostile+'\nline 2');
  assert.equal(h.all(h.content,'script').length,0);assert.equal(h.all(h.content,'img').length,0);
  assert.equal(h.downloads().length,0);assert.equal(h.has('attachment-preview-toolbar').length,0);
  assert.doesNotMatch(h.text(),/文本编码|UTF-8/);
  assert.equal(h.has('attachment-preview-body')[0].attributes['aria-busy'],'false');
});

test('preview requests encode evidence identities and use cancellable local requests',async()=>{
  const h=harness(),pending=h.show({id:'证据&?='},{id:'用例&?='});
  const request=h.requests[0];
  assert.equal(request.url,'/api/attachment-preview?bug_id='+encodeURIComponent('用例&?=')+'&attachment_id='+encodeURIComponent('证据&?='));
  assert.equal(request.init.cache,'no-store');assert.equal(request.init.signal.aborted,false);
  assert.equal(h.all(h.content,'a').length,0);
  h.reply(0,{kind:'text',text:'ok'});await pending;
});

test('a slow previous file can never overwrite a newer file even when abort is ignored',async()=>{
  const h=harness(),first=h.show({id:'old',name:'old.log'}),second=h.show({id:'new',name:'new.log'});
  assert.equal(h.requests[0].init.signal.aborted,true);assert.equal(h.requests[1].init.signal.aborted,false);
  h.reply(1,{kind:'text',text:'new file'});await second;
  h.reply(0,{kind:'text',text:'stale file'});await first;
  assert.equal(h.title.textContent,'new.log');assert.equal(h.one('pre').textContent,'new file');
});

test('close during JSON decoding aborts the request and suppresses late content',async()=>{
  const h=harness(),decode=deferred(),pending=h.show();
  h.requests[0].resolve({ok:true,json:()=>decode.promise});await tick();
  h.dialog.close();assert.equal(h.requests[0].init.signal.aborted,true);
  decode.resolve({kind:'text',text:'late text'});await pending;
  assert.equal(h.one('pre'),undefined);assert.equal(h.dialog.open,false);
});

test('Escape cancels pending reading and listeners are installed only once',async()=>{
  const h=harness(),first=h.show();h.fire(h.dialog,'cancel');
  assert.equal(h.requests[0].init.signal.aborted,true);assert.equal(h.dialog.open,false);
  h.reply(0,{kind:'text',text:'stale'});await first;
  const second=h.show({id:'next'});h.reply(1,{kind:'text',text:'next'});await second;
  assert.equal(h.dialog.listeners.close.length,1);assert.equal(h.dialog.listeners.cancel.length,1);
});

test('a delayed close event from a previously closed dialog does not abort a reopened preview',async()=>{
  const h=harness();await h.show({name:'shot.png',mime:'image/png'});h.dialog.open=false;
  const pending=h.show();h.fire(h.dialog,'close');
  assert.equal(h.requests[0].init.signal.aborted,false);
  h.reply(0,{kind:'text',text:'reopened'});await pending;assert.equal(h.one('pre').textContent,'reopened');
});

test('native image, video and audio extensions work even with generic MIME and never request text extraction',async()=>{
  for(const [name,tag] of [['shot.webp','img'],['clip.mp4','video'],['clip.mov','video'],['clip.mkv','video'],['clip.webm','video'],['voice.wav','audio'],['voice.mp3','audio'],['voice.amr','audio']]){
    const h=harness();await h.show({name,mime:'application/octet-stream'});
    const media=h.one(tag);assert.ok(media,name);assert.equal(h.requests.length,0,name);assert.equal(h.downloads().length,0);
    if(tag!=='img'){assert.equal(media.controls,true);assert.equal(media.preload,'metadata');assert.notEqual(media.autoplay,true);}
    assert.match(media.src,/^\/api\/attachment\?/);
  }
});

test('native MIME can identify media with an unusual file extension',async()=>{
  for(const [mime,tag] of [['image/png','img'],['video/mp4','video'],['audio/mpeg','audio']]){
    const h=harness();await h.show({name:'evidence.unusual',mime});assert.ok(h.one(tag));assert.equal(h.requests.length,0);
  }
});

test('codec failures direct users to their local file without download controls',async()=>{
  const h=harness();await h.show({name:'clip.mkv',mime:'application/octet-stream'});
  h.fire(h.one('video'),'error');const warning=h.has('attachment-preview-notice warning')[0];
  assert.equal(warning.hidden,false);assert.match(warning.textContent,/编码/);assert.match(warning.textContent,/本机播放器/);
  assert.equal(h.downloads().length,0);
});

test('closing or changing media stops playback, clears resources, and ignores detached media errors',async()=>{
  const h=harness();await h.show({name:'voice.mp3'});const audio=h.one('audio');
  await h.show({name:'clip.mp4'});assert.equal(audio.pauseCount,1);assert.equal(audio.loadCount,1);assert.equal(audio.src,undefined);
  const video=h.one('video');h.dialog.close();assert.equal(video.pauseCount,1);assert.equal(video.loadCount,1);assert.equal(video.src,undefined);
  h.fire(video,'error');assert.equal(h.has('attachment-preview-notice warning')[0].hidden,true);
});

test('PDF preserves its native reading tools without an extra application toolbar and clears on close',async()=>{
  const h=harness();await h.show({name:'测试 PDF.pdf',mime:'application/pdf'});
  const frame=h.one('iframe'),links=h.all(h.content,'a');
  assert.match(frame.src,/^\/api\/attachment\?/);assert.equal(frame.title,'测试 PDF.pdf');
  assert.equal(links.length,0);assert.doesNotMatch(frame.src,/#.*toolbar=0/);
  assert.doesNotMatch(h.text(),/PDF 在本机|下载|新窗口/);assert.equal(h.requests.length,0);
  h.dialog.close();assert.equal(frame.src,undefined);
});

test('HTTP failures retain a useful error without adding file actions',async()=>{
  const h=harness(),pending=h.show();h.reply(0,{error:'原文件已移动，请重新扫描。'},404);await pending;
  assert.match(h.text(),/预览没有加载成功/);assert.match(h.text(),/原文件已移动/);assert.equal(h.downloads().length,0);
});

test('network failure and invalid responses do not leave the modal in a loading state',async()=>{
  const h=harness(),pending=h.show();h.requests[0].reject(new TypeError('Failed to fetch'));await pending;
  assert.match(h.text(),/无法连接本地工具/);assert.equal(h.has('attachment-preview-body')[0].attributes['aria-busy'],'false');
  const second=h.show();h.requests[1].resolve({ok:true,json:async()=>{throw new SyntaxError('invalid');}});await second;
  assert.match(h.text(),/预览没有加载成功/);assert.equal(h.downloads().length,0);
});

test('unsupported files have a readable fallback rather than an empty preview',async()=>{
  const h=harness(),pending=h.show({name:'dump.bin',mime:'application/octet-stream'});
  h.reply(0,{kind:'unsupported',message:'此文件为二进制格式，请使用本机工具查看。'});await pending;
  assert.match(h.text(),/暂不支持直接预览/);assert.match(h.text(),/二进制格式/);assert.equal(h.downloads().length,0);
});

test('workbook sheet selection preserves all text and distinguishes truncated sheets',async()=>{
  const h=harness(),pending=h.show({name:'cases.xlsx',mime:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
  const hostile='<svg onload=alert(1)>';
  h.reply(0,{kind:'table',sheets:[
    {name:hostile,rows:[['编号','备注'],['=HYPERLINK("bad")',hostile],['second']],truncated:true},
    {name:'工作表二',rows:[['标题'],['safe second sheet']]}
  ]});await pending;
  assert.equal(h.one('select').children[0].textContent,hostile);assert.match(h.text(),/=HYPERLINK/);assert.match(h.text(),/部分预览/);
  assert.equal(h.all(h.content,'svg').length,0);assert.equal(h.all(h.content,'td').length,4);
  const select=h.one('select');select.value='1';h.fire(select,'change');
  assert.match(h.text(),/safe second sheet/);assert.doesNotMatch(h.text(),/=HYPERLINK/);assert.doesNotMatch(h.text(),/部分预览/);
});

test('document previews disclose extracted text and preserve source contents literally',async()=>{
  const h=harness(),pending=h.show({name:'report.docx'});
  h.reply(0,{kind:'document',text:'[步骤]\n<script>unsafe</script>',notice:'不含嵌入对象。',truncated:true});await pending;
  assert.match(h.text(),/正文文字/);assert.match(h.text(),/原始排版/);assert.match(h.text(),/不含嵌入对象/);
  assert.equal(h.one('pre').textContent,'[步骤]\n<script>unsafe</script>');assert.match(h.text(),/部分预览/);assert.equal(h.all(h.content,'script').length,0);
});

test('ZIP previews list paths and sizes without creating links or extracting entries',async()=>{
  const h=harness(),pending=h.show({name:'logs.zip',mime:'application/zip'});
  h.reply(0,{kind:'archive',entries:[{name:'../<script>run</script>.exe',size:7,directory:false},{name:'folder/',size:0,directory:true}]});await pending;
  assert.match(h.text(),/不会解压/);assert.match(h.text(),/\.\.\/<script>run<\/script>\.exe/);assert.match(h.text(),/7 B/);assert.match(h.text(),/文件夹/);
  assert.equal(h.all(h.content,'script').length,0);assert.equal(h.all(h.content,'a').length,0);
});

test('empty documents, sheets and archives each give an explicit state',async()=>{
  for(const [payload,expected] of [
    [{kind:'text',text:''},/没有可显示的文字/],
    [{kind:'table',sheets:[]},/没有可预览的内容/],
    [{kind:'table',sheets:[{name:'empty',rows:[]}]},/没有可预览的内容/],
    [{kind:'archive',entries:[]},/没有可列出的文件/]
  ]){
    const h=harness(),pending=h.show();h.reply(0,payload);await pending;assert.match(h.text(),expected);assert.equal(h.downloads().length,0);
  }
});

test('backdrop clicks close the viewer while text selection and content clicks remain inside',async()=>{
  const h=harness(),pending=h.show();h.reply(0,{kind:'text',text:'selectable local log'});await pending;
  h.fire(h.dialog,'click',{target:h.one('pre'),clientX:400,clientY:400});
  assert.equal(h.dialog.open,true);
  h.fire(h.dialog,'click',{clientX:100,clientY:100});assert.equal(h.dialog.open,true);
  h.fire(h.dialog,'click',{clientX:400,clientY:400});assert.equal(h.dialog.open,false);
});

test('single-sheet tables have no redundant selector while Office explanations stay collapsed',async()=>{
  const h=harness(),pending=h.show({name:'single.xlsx'});
  h.reply(0,{kind:'table',sheets:[{name:'Only sheet',rows:[['Title'],['Value']]}],notice:'Dates may show saved values.'});await pending;
  assert.equal(h.one('select'),undefined);assert.equal(h.one('td').textContent,'Value');
  const details=h.one('details');assert.ok(details);assert.equal(details.open,false);
  assert.equal(h.has('attachment-preview-row-count').length,0);
});
