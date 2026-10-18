/* BugDesk local workbench. User-controlled content is rendered via text/value only. */
"use strict";
/* Appearance bootstrap: run before styles to avoid a flash of the wrong theme. */
(() => {
  const valid=value=>value==='light'||value==='dark',key='bugdesk.theme';
  let preference='';
  // Cookies retain this harmless browser preference when the local server changes ports.
  try{preference=/(?:^|;\s*)bugdesk_theme=(light|dark)(?:;|$)/.exec(document.cookie||'')?.[1]||'';}catch{}
  if(!preference){try{const stored=localStorage.getItem(key);if(valid(stored))preference=stored;}catch{}}
  const system=window.matchMedia?.('(prefers-color-scheme: dark)');
  function apply(theme){document.documentElement.dataset.theme=theme;window.dispatchEvent(new Event('bugdesk-theme-change'));}
  function set(theme){
    if(!valid(theme))return;
    preference=theme;
    try{localStorage.setItem(key,theme);}catch{}
    try{document.cookie='bugdesk_theme='+theme+'; Path=/; Max-Age=31536000; SameSite=Strict';}catch{}
    apply(theme);
  }
  window.bugDeskAppearance={set,toggle:()=>set(document.documentElement.dataset.theme==='dark'?'light':'dark')};
  system?.addEventListener?.('change',()=>{if(!preference)apply(system.matches?'dark':'light');});
  window.addEventListener('storage',event=>{if(event.key===key&&valid(event.newValue)){preference=event.newValue;apply(preference);}});
  apply(preference||(system?.matches?'dark':'light'));
})();
/* UI icons */
const ICONS = {
  moon:'<path d="M20.9 13A9 9 0 0 1 11 3.1 9 9 0 1 0 20.9 13Z"/>',
  sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.4 1.4m11.2 11.2L19 19M5 19l1.4-1.4M17.6 6.4 19 5"/>',
  bug:'<path d="M9 9h6v8a3 3 0 0 1-6 0V9Z"/><path d="M9 9a3 3 0 0 1 6 0M12 9v11M5 10l4 2m6 0 4-2M5 16h4m6 0h4M7 21l3-3m4 0 3 3M8 3l2 3m4 0 2-3"/>',
  layers:'<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/>',
  folder:'<path d="M3 7a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/>',
  external:'<path d="M14 3h7v7m0-7-11 11"/><path d="M10 5H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5"/>',
  help:'<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 4.5 1.5c-1 1-2 1-2 3M12 17h.01"/>',
  power:'<path d="M12 2v10M6 5a9 9 0 1 0 12 0"/>',
  download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4"/>',
  refresh:'<path d="M20 7v5h-5M4 17v-5h5"/><path d="M5 7a8 8 0 0 1 14-2l1 2M4 17l1 2a8 8 0 0 0 14-2"/>',
  edit:'<path d="m15 4 5 5M4 20l4-1L20 7a2 2 0 0 0-4-4L4 15v5Z"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  send:'<path d="m3 3 18 7-8 4-4 8-6-19Z"/><path d="m21 10-12 4"/>',
  sliders:'<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2" fill="currentColor" stroke="none"/><circle cx="15" cy="12" r="2" fill="currentColor" stroke="none"/><circle cx="8" cy="18" r="2" fill="currentColor" stroke="none"/>',
  chevron:'<path d="m9 5 7 7-7 7"/>',
  search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
  close:'<path d="m6 6 12 12M18 6 6 18"/>',
  arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>',
  clip:'<path d="m8 13 6-6a3 3 0 0 1 4 4L9 20a5 5 0 0 1-7-7L13 2"/>',
  file:'<path d="M14 2H5v20h14V7l-5-5Zm0 0v5h5M8 12h8M8 16h8"/>',
  copy:'<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
  image:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-7 5 8"/>',
  video:'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m10 9 5 3-5 3V9Z"/>',
  lock:'<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4M12 14v3"/>',
  left:'<path d="m15 5-7 7 7 7"/>',
  right:'<path d="m9 5 7 7-7 7"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'
};
const $ = id => document.getElementById(id);
function icon(name) { const span = document.createElement('span'); span.dataset.icon = name; span.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">'+(ICONS[name]||ICONS.file)+'</svg>'; return span; }
function hydrateIcons(root = document) { root.querySelectorAll('[data-icon]').forEach(el => { if (!el.firstChild) el.append(icon(el.dataset.icon).firstChild); }); }
function node(tag, className, content) { const el = document.createElement(tag); if(className) el.className = className; if(content !== undefined) el.textContent = content; return el; }
function button(text, className, action, iconName) { const b=node('button',className); b.type='button'; if(iconName)b.append(icon(iconName)); if(text)b.append(node('span','',text)); if(action)b.addEventListener('click',action); return b; }
function safeLink(url, label, className='') { const a=node('a',className,label); try { const parsed=new URL(url,location.origin); if(!['http:','https:'].includes(parsed.protocol))return node('span',className,label); a.href=parsed.href; a.target='_blank'; a.rel='noopener noreferrer'; } catch {return node('span',className,label);} return a; }
let state = {settings:{},bugs:[],warnings:[],profiles:[],connection:{connected:false,first_verified:false},job:{running:false}};
let token='', currentId='', filter='all', search='', editorTab='description';
let dirtyBugs=new Map(), dirtySettings=null, dirtyProfiles=null, dirtyActiveProfile=null, saveTimer=null, saveChain=Promise.resolve(), activeSaves=0, settingsDraft={}, options={};
let reviewIds=[], reviewSnapshots=[], submitIds=[], pollTimer=null, heartbeatTimer=null, scanBusy=false, batchBusy=false, shuttingDown=false;
let activeChoice=null, choiceSerial=0, menuSerial=0, menuBusy=false, menuContext='', menuWarnings=[], settingsComposing=false, menusRenderPending=false;
const STATUS = {draft:'待补充',needs_review:'待审核',ready:'已审核',submitted:'已提交',submitting:'提交中',failed:'提交失败',uncertain:'需核对',partial:'附件待补'};
const TYPES=[['codeerror','代码错误'],['interface','界面问题'],['config','配置相关'],['install','安装部署'],['performance','性能问题'],['security','安全问题'],['standard','标准规范'],['automation','测试脚本'],['designdefect','设计缺陷'],['others','其他']];
const SEVERITIES=[['1','致命'],['2','严重'],['3','一般'],['4','轻微']];
const PRIORITIES=[['1','高'],['2','中'],['3','低'],['4','极低']];
const BUG_OVERRIDE_KEYS=['type','severity','pri','assignedTo','probability'];
function priorityItems(){return options.priorities?.length?options.priorities.map(item=>[String(item.value),String(item.label)]):PRIORITIES;}
function priorityBadge(value){const pill=node('span','context-pill','优先级 · '+optionLabel(priorityItems(),value));pill.dataset.context='priority';return pill;}
function refreshPriorityBadge(bug){const pill=$('editorPanel').querySelector('[data-context="priority"]');if(pill)pill.textContent='优先级 · '+optionLabel(priorityItems(),effectiveSettings(bug).pri||'4');}
function toast(message, error=false) { const t=node('div','toast'+(error?' error':''),message); $('toastContainer').append(t); setTimeout(()=>t.remove(),error?7000:4200); }
function errorMessage(error) {return error?.message || '操作未完成，请再试一次。';}
async function api(path, data, config={}) {
  const init={method:data===undefined?'GET':'POST',cache:'no-store',headers:{}};
  if(data!==undefined){init.headers['Content-Type']='application/json';init.headers['X-BugDesk-Token']=token;init.body=JSON.stringify(data);}
  try {const r=await fetch(path,init);let payload;try{payload=await r.json();}catch{throw new Error('工具服务没有返回有效结果，请重新打开 BugDesk。');}if(!r.ok||payload.error)throw new Error(payload.error||'操作未完成。');return payload;}catch(e){if(e instanceof TypeError)throw new Error('无法连接本地工具，请重新打开 BugDesk。');throw e;}
}
function currentBug(){return state.bugs.find(b=>b.id===currentId);}
function locked(bug){return batchBusy || state.job?.running || ['submitted','submitting','uncertain','partial'].includes(bug?.status) || !!bug?.remote_id;}
function complete(bug){return ['title','steps','actual','expected'].every(k=>String(bug[k]||'').trim());}
function missing(bug){return [['title','标题'],['steps','复现步骤'],['actual','实际结果'],['expected','预期结果']].filter(([k])=>!String(bug[k]||'').trim()).map(([,v])=>v);}
function derivedStatus(bug){if(['submitted','submitting','uncertain','partial','failed'].includes(bug.status))return bug.status;return complete(bug)?(bug.reviewed?'ready':'needs_review'):'draft';}
function statusBadge(bug){const s=derivedStatus(bug);return node('span','status '+s,STATUS[s]||s);}
function shownBugs(){return state.bugs.filter(b=>{const s=derivedStatus(b);if(filter==='todo'&&!['draft','needs_review','failed','uncertain','partial'].includes(s))return false;if(filter==='ready'&&s!=='ready')return false;if(filter==='submitted'&&s!=='submitted')return false;if(search&&![...['title','steps','actual','expected','original_title'].map(k=>b[k]),...Object.values(b.case_source||{})].some(v=>String(v||'').toLowerCase().includes(search)))return false;return true;});}
function selectedBugs(){return state.bugs.filter(b=>b.selected);}
function includedAttachments(bug){const excluded=new Set(bug.excluded_attachments||[]);return (bug.attachments||[]).filter(a=>!excluded.has(a.id));}
function formatBytes(n){if(n>=1024*1024)return (n/(1024*1024)).toFixed(1)+' MB';if(n>=1024)return Math.round(n/1024)+' KB';return n+' B';}
function attachmentUrl(bug,a){return '/api/attachment?bug_id='+encodeURIComponent(bug.id)+'&attachment_id='+encodeURIComponent(a.id);}
function effectiveSettings(bug){return {...state.settings,...bug.overrides};}
function fullTitle(bug){const prefix=String(effectiveSettings(bug).title_prefix||'').trim();return prefix&&!bug.title.startsWith(prefix)?prefix+bug.title:bug.title;}
function combinedPreconditions(bug){return [...new Set([effectiveSettings(bug).preconditions||'',bug.preconditions||''].map(v=>String(v).trim()).filter(Boolean))].join('\n\n');}
function reportText(bug){const pre=combinedPreconditions(bug);return fullTitle(bug)+'\n\n'+(pre?'[前置条件]\n'+pre+'\n\n':'')+'[步骤]\n'+(bug.steps||'')+'\n\n[结果]\n'+bug.actual+'\n\n[期望]\n'+bug.expected;}
function localEdit(bug,changes,clearReview=true){if(batchBusy)return;bug=state.bugs.find(b=>b.id===bug.id)||bug;if(clearReview)changes.reviewed=false;Object.assign(bug,changes);if(!['submitted','submitting','uncertain','partial'].includes(bug.status))bug.status=complete(bug)?(bug.reviewed?'ready':'needs_review'):'draft';dirtyBugs.set(bug.id,{...(dirtyBugs.get(bug.id)||{}),...changes});renderSaveStatus();renderChrome();scheduleSave();}
function scheduleSave(){clearTimeout(saveTimer);saveTimer=setTimeout(()=>flushSave().catch(e=>toast(errorMessage(e),true)),650);}
function overlayPending(next){for(const[id,patch]of dirtyBugs){const b=next.bugs.find(b=>b.id===id);if(b)Object.assign(b,patch);}if(dirtySettings)Object.assign(next.settings,dirtySettings);if(dirtyProfiles)next.profiles=dirtyProfiles;if(dirtyActiveProfile!==null)next.active_profile=dirtyActiveProfile;return next;}
function adoptStateKeepingBugs(next){const previous=new Map(state.bugs.map(b=>[b.id,b]));next.bugs=next.bugs.map(b=>{const stable=previous.get(b.id);if(stable){Object.assign(stable,b);return stable;}return b;});state=next;}
function hasBufferedSave(){return !!(dirtyBugs.size||dirtySettings||dirtyProfiles||dirtyActiveProfile!==null);}
function hasPendingSave(){return activeSaves>0||hasBufferedSave();}
function renderSaveStatus(failed=false){$('saveStatus').textContent=activeSaves>0?'正在保存…':failed?'保存失败 · Ctrl+S 重试':hasBufferedSave()?'等待保存…':'已自动保存';}
function flushSave(){
  clearTimeout(saveTimer);saveTimer=null;
  saveChain=saveChain.catch(()=>{}).then(async()=>{
    if(!hasBufferedSave())return;
    const snapshot=new Map(dirtyBugs),settings=dirtySettings,profiles=dirtyProfiles,activeProfile=dirtyActiveProfile;
    ++activeSaves;dirtyBugs.clear();dirtySettings=null;dirtyProfiles=null;dirtyActiveProfile=null;
    const payload={};if(snapshot.size)payload.bugs=[...snapshot].map(([id,patch])=>({id,...patch}));if(settings)payload.settings=settings;if(profiles)payload.profiles=profiles;if(activeProfile!==null)payload.active_profile=activeProfile;
    let failed=false;renderSaveStatus();
    try{const next=await api('/api/save',payload);adoptStateKeepingBugs(overlayPending(next));renderChrome();}
    catch(e){failed=true;for(const[id,patch]of snapshot)dirtyBugs.set(id,{...patch,...(dirtyBugs.get(id)||{})});if(settings)dirtySettings={...settings,...(dirtySettings||{})};if(profiles&&!dirtyProfiles)dirtyProfiles=profiles;if(activeProfile!==null&&dirtyActiveProfile===null)dirtyActiveProfile=activeProfile;throw e;}
    finally{--activeSaves;renderSaveStatus(failed);}
  });
  return saveChain;
}
async function replaceState(next){state=next;++menuSerial;menuBusy=false;restoreCachedMenus(next);dirtyBugs.clear();dirtySettings=null;dirtyProfiles=null;dirtyActiveProfile=null;if(!state.bugs.some(b=>b.id===currentId))currentId=state.bugs[0]?.id||'';if(state.root_dir)$('folderInput').value=state.root_dir;renderChrome();renderEditor();}
async function switchBatch(loadState){if(state.job?.running||batchBusy)return false;batchBusy=true;renderChrome();renderEditor();try{await flushSave();await replaceState(await loadState());return true;}finally{batchBusy=false;renderChrome();renderEditor();}}
function renderChrome(){
  const bugs=state.bugs,ready=bugs.filter(b=>derivedStatus(b)==='ready').length,submitted=bugs.filter(b=>derivedStatus(b)==='submitted').length;
  $('listCount').textContent=bugs.length;$('countAll').textContent=bugs.length;$('countTodo').textContent=bugs.filter(b=>['draft','needs_review','failed','uncertain','partial'].includes(derivedStatus(b))).length;$('countReady').textContent=ready;$('countSubmitted').textContent=submitted;
  const parts=(state.root_dir||'').replace(/\\/g,'/').split('/').filter(Boolean);$('batchName').textContent=parts.at(-1)||'选择 Bug 文件夹';$('batchPath').textContent=state.root_dir||'选择当天的 Bug 文件夹';$('demoBadge').hidden=!state.demo;$('batchName').title=state.root_dir||'选择 Bug 文件夹';
  $('warningStrip').hidden=!state.warnings?.length;$('warningStrip').textContent=(state.warnings||[]).join('；');
  const c=state.connection||{};$('connectionDot').classList.toggle('connected',!!c.connected);$('connectionLabel').textContent=c.connected?'已连接禅道':'连接禅道';
  const summary=$('sharedSummary');summary.replaceChildren();const s=state.settings;const fragments=[['产品',s.product_name],['版本',s.build_name],['指派',s.assignee_name],['项目',s.project_name]];const named=fragments.filter(([,v])=>v);if(named.length)named.forEach(([label,value])=>summary.append(node('span','',label+' · '+value)));else summary.textContent='产品、版本、指派人等，只需设置一次';
  $('selectAll').disabled=batchBusy||!!state.job?.running;const visible=shownBugs();$('selectAll').checked=!!visible.length&&visible.every(b=>b.selected);$('selectAll').indeterminate=visible.some(b=>b.selected)&&!$('selectAll').checked;
  const selected=selectedBugs();$('selectedCount').textContent='已选 '+selected.length+' 条';$('reviewSelectedButton').disabled=batchBusy||!selected.some(b=>!locked(b))||state.job?.running;$('submitButton').disabled=batchBusy||!!state.demo||!!state.job?.running||!selected.length;$('submitLabel').textContent=batchBusy?'正在切换批次…':state.demo?'示例数据不能提交':state.job?.running?'提交进行中…':'提交已选 Bug'+(selected.length?'（'+selected.length+'）':'');
  for(const id of ['scanButton','browseButton','folderInput','settingsButton','connectionButton','openBatchButton','importButton','exportButton','casePasteButton','workBuddyButton','shutdownButton'])$(id).disabled=batchBusy||!!state.job?.running||((id==='scanButton'||id==='browseButton')&&scanBusy);
  $('openBatchButton').disabled=batchBusy||!state.root_dir||state.demo||!!state.job?.running;
  renderList();refreshEditorNavigation();const bug=currentBug();if(bug){refreshPriorityBadge(bug);refreshBugSettings(bug);const badge=$('editorStatus');if(badge){badge.replaceChildren(statusBadge(bug));}const foot=$('editorFooterState');if(foot){foot.replaceChildren(icon(locked(bug)?'lock':complete(bug)?'check':'edit'));foot.append(node('span','',batchBusy?'正在保存并切换批次…':locked(bug)?'此条已进入提交流程':bug.reviewed?'审核完成，可以提交':complete(bug)?'信息齐全，请审核后提交':'还需补充：'+missing(bug).join('、')));}const review=$('reviewCurrentButton');if(review)review.disabled=locked(bug)||!complete(bug);}
}
function renderList(){const list=$('bugList'),scrollTop=list.scrollTop;list.replaceChildren();const bugs=shownBugs();if(!bugs.length){list.append(node('div','list-empty',state.bugs.length?'没有符合筛选的 Bug\n试试更换关键词或筛选条件。':'扫描当天的文件夹后，\nBug 会出现在这里。'));return;}bugs.forEach((bug,index)=>{const card=node('div','bug-item'+(bug.id===currentId?' active':''));card.setAttribute('role','listitem');card.tabIndex=0;const check=node('input');check.type='checkbox';check.checked=!!bug.selected;check.disabled=batchBusy||!!state.job?.running;check.setAttribute('aria-label','选择 '+bug.title);check.addEventListener('click',e=>e.stopPropagation());check.addEventListener('change',()=>localEdit(bug,{selected:check.checked},false));const content=node('div','bug-item-main');content.append(node('div','bug-item-title',bug.title||'未填写标题'));const meta=node('div','bug-meta');meta.append(statusBadge(bug));const count=node('span','attachment-count');count.append(icon('clip'),node('span','',includedAttachments(bug).length+' 附件'));meta.append(count);content.append(meta);card.append(check,content);card.addEventListener('click',()=>selectBug(bug.id));card.addEventListener('keydown',e=>{if(e.target===card&&(e.key==='Enter'||e.key===' ')){e.preventDefault();selectBug(bug.id);}});list.append(card);});list.scrollTop=scrollTop;}
async function selectBug(id){if(batchBusy||id===currentId)return;try{await flushSave();if(batchBusy)return;currentId=id;editorTab='description';renderChrome();renderEditor();$('bugList').querySelector('.bug-item.active')?.scrollIntoView({block:'nearest',inline:'nearest'});}catch(e){toast(errorMessage(e),true);}}
function sectionReport(container,label,value){const s=node('div','report-section');s.append(node('strong','',label));s.append(node('p',value?'':'empty-value',value||'尚未填写'));container.append(s);}
function reportContext(bug){const s=effectiveSettings(bug),context=node('div','preview-context');const probability=(options.probabilities||[]).find(o=>String(o.value)===String(s.probability))?.label||s.probability;[['产品',s.product_name],['项目',s.project_name],['执行',s.execution_name],['模块',s.module_name],['版本',s.build_name],['指派人',s.assignee_name||s.assignedTo],['反馈者',s.feedbackBy],['Bug 类型',s.type?optionLabel(TYPES,s.type):''],['发生概率',probability],['严重程度',s.severity?optionLabel(SEVERITIES,s.severity):''],['优先级',s.pri?optionLabel(priorityItems(),s.pri):''],['操作系统',s.os],['来源用例',bug.case_source?.case_id]].filter(([,v])=>v).forEach(([label,value])=>context.append(node('span','',label+'：'+value)));return context;}
function buildReport(bug,heading=true){const report=node('div','report-preview');if(heading)report.append(node('h3','',fullTitle(bug)||'未填写标题'));const context=reportContext(bug);if(context.childNodes.length)report.append(context);const pre=combinedPreconditions(bug);if(pre)sectionReport(report,'[前置条件]',pre);sectionReport(report,'[步骤]',bug.steps||'');sectionReport(report,'[结果]',bug.actual);sectionReport(report,'[期望]',bug.expected);return report;}
function renderEditor(){const panel=$('editorPanel'),bug=currentBug();if(!bug){renderEmpty();return;}const isLocked=locked(bug);panel.replaceChildren();const scroll=node('div','editor-scroll'+(isLocked?' locked':''));const top=node('div','editor-top'),crumb=node('div','editor-breadcrumb');crumb.append(icon('folder'),node('span','',state.demo?'示例 Bug':'Bug '+(state.bugs.indexOf(bug)+1)+' / '+state.bugs.length));const tools=node('div','editor-tools');const open=button('', 'icon-button',async()=>{try{await api('/api/open-folder',{bug_id:bug.id});}catch(e){toast(errorMessage(e),true);}},'external');open.title='打开此 Bug 的原始文件夹';open.setAttribute('aria-label',open.title);open.disabled=state.demo;tools.append(open);top.append(crumb,tools);scroll.append(top);
  const title=node('textarea','title-input');title.value=bug.title;title.rows=1;title.setAttribute('aria-label','Bug 标题');title.placeholder='请输入 Bug 标题';title.disabled=isLocked;title.addEventListener('input',()=>{autoHeight(title);localEdit(bug,{title:title.value});});scroll.append(title);requestAnimationFrame(()=>autoHeight(title));
  const badge=node('span');badge.id='editorStatus';badge.append(statusBadge(bug));crumb.append(badge);
  if(bug.error){scroll.append(node('div','notice warning',bug.error));}if(['uncertain','partial'].includes(bug.status)||bug.status==='failed'&&bug.remote_id){const note=node('div','notice warning');note.append(node('div','',bug.status==='partial'?'Bug 已创建，附件未确认完整。请到禅道补齐附件后记录完成。':'提交结果需要核对。先在禅道查找这条 Bug，再记录核对结果。'));if(bug.remote_url)note.append(safeLink(bug.remote_url,'到禅道核对','text-button'));note.append(button('记录核对结果','button secondary',()=>openResolve(bug)));scroll.append(note);}else if(bug.status==='submitted'){const n=node('div','notice info');n.append(node('span','','已成功提交'+(bug.remote_id?' · Bug #'+bug.remote_id:'')));if(bug.remote_url){const a=safeLink(bug.remote_url,'查看禅道 Bug','text-button');a.style.marginLeft='12px';n.append(a);}scroll.append(n);}
  const toolbar=node('div','editor-toolbar'),tabs=node('div','tab-bar');[['description','问题描述','edit'],['attachments','附件','clip'],['preview','提交预览','file']].forEach(([value,label,ico])=>{const b=button(label,'tab'+(editorTab===value?' active':''),()=>{editorTab=value;renderEditor();},ico);if(value==='attachments')b.append(node('span','tab-count',includedAttachments(bug).length));tabs.append(b);});toolbar.append(tabs,bugSettingsControl(bug,isLocked));scroll.append(toolbar);
  if(editorTab==='description')renderDescription(scroll,bug,isLocked);if(editorTab==='attachments')renderAttachments(scroll,bug,isLocked);if(editorTab==='preview'){scroll.append(node('p','caption','下面是提交到禅道的完整描述。可复制内容，或检查公共信息是否正确。'),buildReport(bug),button('复制完整描述','button secondary copy-preview',()=>copyText(reportText(bug)),'copy'));}
  const foot=node('div','editor-footer'),footState=node('span','footer-state');footState.id='editorFooterState';const actions=node('div','footer-actions');const navigation=shownBugs(),position=navigation.findIndex(item=>item.id===bug.id);const prev=button('上一条','button navigation-button',()=>adjacent(-1),'left');prev.id='previousBugButton';prev.title='上一条（Alt + ↑）';prev.setAttribute('aria-label',prev.title);prev.disabled=position<=0;const next=button('下一条','button navigation-button',()=>adjacent(1),'right');next.id='nextBugButton';next.title='下一条（Alt + ↓）';next.setAttribute('aria-label',next.title);next.disabled=position<0||position>=navigation.length-1;const review=button(bug.reviewed?'重新查看审核':'审核这一条','button primary',()=>openReview([bug.id]),'check');review.id='reviewCurrentButton';review.title='审核当前 Bug（Ctrl + Enter）';review.disabled=isLocked||!complete(bug);actions.append(prev,next,review);foot.append(footState,actions);panel.append(scroll,foot);renderChrome();}
function autoHeight(el){el.style.height='auto';el.style.height=Math.max(44,el.scrollHeight+2)+'px';}
function optionLabel(items,value){return items.find(([v])=>v===String(value))?.[1]||String(value);}
function makeSelect(items,value,emptyLabel){const s=node('select');if(emptyLabel){const o=node('option','',emptyLabel);o.value='';s.append(o);}items.forEach(([v,l])=>{const o=node('option','',l);o.value=v;s.append(o);});if(value&&!items.some(([v])=>v===String(value))){const o=node('option','',String(value));o.value=value;s.append(o);}s.value=String(value??'');return s;}
function renderDescription(scroll,bug,isLocked){
  const preDetails=node('details','advanced preconditions-disclosure');const preSummary=node('summary','','前置条件（选填）');preDetails.append(preSummary);if(state.settings.preconditions)preDetails.append(node('p','field-help','公共前置条件：'+state.settings.preconditions));const pre=editorField('preconditions','本条额外前置条件','例如：已登录账号，网络正常，使用指定测试版本。',bug,isLocked,null);pre.style.marginTop='14px';preDetails.append(pre);scroll.append(preDetails);
  const stepsField=editorField('steps','复现步骤','1. 进入哪个页面或功能\n2. 做了什么操作\n3. 在哪一步出现问题',bug,isLocked,'1');if(state.settings.steps_template&&!bug.steps&&!isLocked){stepsField.append(button('填入公共步骤模板','text-button',()=>{localEdit(bug,{steps:state.settings.steps_template});renderEditor();}));}scroll.append(stepsField);
  const actualField=editorField('actual','实际结果','记录你实际看到的异常现象。',bug,isLocked,'2');const heading=actualField.firstElementChild;if(!isLocked){heading.append(button('标题填入实际结果','text-button',()=>{if(bug.actual.trim()&&!confirm('实际结果已经有内容，确定用 Bug 标题替换吗？'))return;localEdit(bug,{actual:bug.title});renderEditor();}));}
  const results=node('div','editor-results');results.append(actualField,editorField('expected','预期结果','按照需求，正确的行为应该是什么？',bug,isLocked,'3'));scroll.append(results);
}
function bugOverrideCount(bug){return BUG_OVERRIDE_KEYS.filter(key=>String(bug.overrides?.[key]??'').trim()!=='').length;}
function refreshBugSettings(bug){
  const count=bugOverrideCount(bug),summary=$('bugSettingsSummary'),status=$('bugSettingsStatus'),reset=$('bugSettingsReset');
  if(summary)summary.classList.toggle('has-overrides',count>0);
  if(status)status.textContent=count?'已修改 '+count+' 项':'跟随公共配置';
  if(reset)reset.disabled=locked(bug)||count===0;
  if(editorTab==='preview'){
    const context=$('editorPanel').querySelector('.report-preview .preview-context');
    if(context)context.replaceChildren(...reportContext(bug).childNodes);
  }
}
function resetBugOverrides(bug){
  bug=state.bugs.find(item=>item.id===bug.id)||bug;
  if(locked(bug)||!bugOverrideCount(bug))return false;
  const overrides={...bug.overrides};[...BUG_OVERRIDE_KEYS,'assignee_name'].forEach(key=>delete overrides[key]);
  localEdit(bug,{overrides});return true;
}
function bugSettingsControl(bug,isLocked){
  const details=node('details','header-popover bug-settings');details.id='bugSettings';
  const summary=node('summary');summary.id='bugSettingsSummary';summary.setAttribute('aria-controls','bugSettingsPanel');
  const status=node('span','bug-settings-status');status.id='bugSettingsStatus';
  const chevron=node('span','bug-settings-chevron');chevron.append(icon('chevron'));
  summary.append(icon('sliders'),node('span','bug-settings-label','本条设置'),node('span','bug-settings-separator','·'),status,chevron);
  const panel=node('section','header-popup bug-settings-panel');panel.id='bugSettingsPanel';panel.setAttribute('aria-label','本条 Bug 设置');
  const heading=node('div','bug-settings-heading');heading.append(node('strong','','本条设置'));
  const fields=node('div','override-fields');
  const reset=button('恢复公共配置','text-button',()=>{if(resetBugOverrides(bug)){renderBugOverrideFields(fields,bug,locked(bug));summary.focus();}});reset.id='bugSettingsReset';
  heading.append(reset);panel.append(heading,node('p','bug-settings-hint',isLocked?'此条已锁定，仅可查看设置。':'仅对当前 Bug 生效，未单独设置的项目跟随公共配置。'),fields);
  renderBugOverrideFields(fields,bug,isLocked);details.append(summary,panel);
  details.addEventListener('toggle',()=>{if(details.open)closeHeaderPanels(details);});
  return details;
}
function renderBugOverrideFields(fields,bug,isLocked){
  fields.replaceChildren();
  [['type','Bug 类型',TYPES],['severity','严重程度',SEVERITIES],['pri','优先级',priorityItems()]].forEach(([key,label,items])=>{
    const field=node('label','field');field.append(node('span','',label));
    const select=makeSelect(items,bug.overrides?.[key]||'','跟随公共配置');select.disabled=isLocked;
    select.addEventListener('change',()=>{if(locked(bug))return;const overrides={...bug.overrides};if(select.value)overrides[key]=select.value;else delete overrides[key];localEdit(bug,{overrides});});
    field.append(select);fields.append(field);
  });
  const assignment=node('label','field');assignment.append(node('span','','单独指派给'));
  if(options.users?.length){
    const select=makeSelect(options.users.map(user=>[String(user.value),user.label]),bug.overrides?.assignedTo||'','跟随公共配置');select.disabled=isLocked;
    select.addEventListener('change',()=>{if(locked(bug))return;const overrides={...bug.overrides};if(select.value){overrides.assignedTo=select.value;overrides.assignee_name=select.selectedOptions[0].textContent;}else{delete overrides.assignedTo;delete overrides.assignee_name;}localEdit(bug,{overrides});});assignment.append(select);
  }else{
    const input=node('input');input.value=bug.overrides?.assignedTo||'';input.placeholder='禅道账号，留空跟随公共配置';input.disabled=isLocked;
    input.addEventListener('input',()=>{if(locked(bug))return;const overrides={...bug.overrides};if(input.value.trim()){overrides.assignedTo=input.value.trim();overrides.assignee_name=input.value.trim();}else{delete overrides.assignedTo;delete overrides.assignee_name;}localEdit(bug,{overrides});});assignment.append(input);
  }
  fields.append(assignment,probabilityOverrideField(bug,isLocked));
}
function editorField(key,label,placeholder,bug,isLocked,num){const f=node('div','field');const heading=node('div','field-heading');const t=node('span','field-title');t.append(node('span','',label));if(key!=='preconditions')t.append(node('i','required-dot'));heading.append(t);f.append(heading);const textarea=node('textarea');textarea.value=bug[key]||'';textarea.placeholder=placeholder;textarea.setAttribute('aria-label',label);textarea.dataset.bugField=key;textarea.disabled=isLocked;if(key==='steps')textarea.rows=4;else textarea.rows=3;if(key==='preconditions')textarea.rows=2;textarea.addEventListener('input',()=>localEdit(bug,{[key]:textarea.value}));f.append(textarea);if(key==='steps')f.style.marginTop='22px';return f;}
function renderAttachments(scroll,bug,isLocked){scroll.append(node('p','caption','附件来自此 Bug 的原始文件夹。取消勾选可暂不上传，原始文件不会被修改。'));const all=bug.attachments||[];if(!all.length){scroll.append(node('div','attachment-empty','这个文件夹还没有附件。添加文件后，重新扫描即可。'));return;}const grid=node('div','attachment-grid'),excluded=new Set(bug.excluded_attachments||[]);all.forEach(a=>{const card=node('div','attachment-card'+(excluded.has(a.id)?' excluded':''));const visual=button('','attachment-visual',()=>showAttachment(bug,a));visual.setAttribute('aria-label','预览 '+a.name);if((a.mime||'').startsWith('image/')){const img=node('img');img.src=attachmentUrl(bug,a);img.alt=a.name;img.loading='lazy';img.addEventListener('error',()=>{img.remove();visual.append(icon('image'));},{once:true});visual.append(img);}else visual.append(icon((a.mime||'').startsWith('video/')?'video':'file'));const body=node('div','attachment-card-body');const title=node('span','attachment-name',a.name);title.title=a.name;body.append(title);const meta=node('div','attachment-card-meta');meta.append(node('span','',formatBytes(a.size||0)));const label=node('label','attach-toggle');const check=node('input');check.type='checkbox';check.checked=!excluded.has(a.id);check.disabled=isLocked;check.setAttribute('aria-label','上传 '+a.name);check.addEventListener('change',()=>{const ids=new Set(bug.excluded_attachments||[]);if(check.checked)ids.delete(a.id);else ids.add(a.id);localEdit(bug,{excluded_attachments:[...ids]});card.classList.toggle('excluded',!check.checked);});label.append(check,node('span','','上传'));meta.append(label);body.append(meta);card.append(visual,body);grid.append(card);});scroll.append(grid);}
function showAttachment(bug,a){$('previewTitle').textContent=a.name;const body=$('previewContent');body.replaceChildren();const url=attachmentUrl(bug,a),mime=a.mime||'';if(mime.startsWith('image/')){const img=node('img');img.src=url;img.alt=a.name;body.append(img);}else if(mime.startsWith('video/')||mime.startsWith('audio/')){const m=node(mime.startsWith('video/')?'video':'audio');m.src=url;m.controls=true;m.preload='metadata';body.append(m);}else{const p=node('p','','此类型附件无法在工具中预览。\n');const a2=node('a','','下载 / 打开附件');a2.href=url;a2.download=a.name;p.append(a2);body.append(p);}$('previewDialog').showModal();}
function renderEmpty(){const panel=$('editorPanel');panel.replaceChildren();const empty=node('div','empty-state'),ill=node('div','empty-illustration');ill.append(icon('folder'));const check=icon('check');check.classList.add('floating-check');ill.append(check);empty.append(ill,node('span','eyebrow','从文件夹开始，告别重复填写'));const title=node('h2');title.append(document.createTextNode('你负责发现问题，'),node('br'),document.createTextNode('BugDesk 帮你整理提交。'));empty.append(title);const p=node('p');p.append(document.createTextNode('每个子文件夹就是一条 Bug。'),node('br'),document.createTextNode('标题、截图和视频会自动整理，公共信息只填一次。'));empty.append(p,button('选择今天的文件夹','button primary',pickAndScan,'folder'),button('先试试示例数据','text-button demo-start',loadDemo,'arrow'));const flow=node('div','empty-flow');['扫描文件夹','→','补充与审核','→','提交禅道'].forEach((t,i)=>flow.append(node(i%2?'b':'span','',t)));empty.append(flow);panel.append(empty);}
function refreshEditorNavigation(){
  const bugs=shownBugs(),index=bugs.findIndex(b=>b.id===currentId);
  const previous=$('previousBugButton'),next=$('nextBugButton');
  if(previous)previous.disabled=batchBusy||index<=0;
  if(next)next.disabled=batchBusy||index<0||index>=bugs.length-1;
}
async function adjacent(direction){const bugs=shownBugs(),idx=bugs.findIndex(b=>b.id===currentId);const next=bugs[idx+direction];if(next)await selectBug(next.id);}
async function copyText(text){try{await navigator.clipboard.writeText(text);toast('完整描述已复制');}catch{toast('浏览器未允许复制，可以在预览中选中文字复制。',true);}}
async function pickAndScan(){if(state.job?.running||scanBusy||batchBusy)return;try{await flushSave();scanBusy=true;renderChrome();$('browseButton').textContent='正在选择…';const result=await api('/api/pick-folder',{});if(result.path){$('folderInput').value=result.path;scanBusy=false;await scanFolder();}}catch(e){toast(errorMessage(e),true);}finally{scanBusy=false;$('browseButton').textContent='选择文件夹';renderChrome();}}
async function scanFolder(){if(state.job?.running||scanBusy||batchBusy)return;const path=$('folderInput').value.trim();if(!path){toast('请先选择或粘贴当天的 Bug 文件夹路径。',true);$('folderInput').focus();return;}try{if(await switchBatch(()=>api('/api/scan',{path}))){closeHeaderPanels();toast(state.bugs.length?'扫描完成 · 找到 '+state.bugs.length+' 条 Bug':'目录已打开，暂时没有找到 Bug 子文件夹。');}}catch(e){toast(errorMessage(e),true);}}
async function loadDemo(){if(state.job?.running||scanBusy||batchBusy)return;try{if(await switchBatch(()=>api('/api/demo',{})))toast('已打开示例数据 · 可以编辑、预览和导出，不会提交到禅道。');}catch(e){toast(errorMessage(e),true);}}
async function openReview(ids){if(batchBusy||state.job?.running)return;try{await flushSave();if(batchBusy)return;const bugs=ids.map(id=>state.bugs.find(b=>b.id===id)).filter(b=>b&&!locked(b));if(!bugs.length){toast('没有可审核的 Bug。',true);return;}const incomplete=bugs.filter(b=>!complete(b));reviewIds=bugs.filter(complete).map(b=>b.id);reviewSnapshots=bugs.filter(complete).map(b=>({id:b.id,review_token:String(b.review_token||'')}));if(!reviewIds.length){toast('请先补齐标题、步骤、实际结果和预期结果。',true);return;}$('reviewTitle').textContent=reviewIds.length>1?'审核 '+reviewIds.length+' 条 Bug':'审核这一条 Bug';$('reviewIntro').textContent='请逐条阅读完整描述，确认公共信息、操作、结果和附件符合实际测试情况。'+(incomplete.length?'有 '+incomplete.length+' 条信息未完整，本次不参与审核。':'');$('reviewHint').textContent=reviewIds.length+' 条完整 Bug';const list=$('reviewItems');list.replaceChildren();reviewIds.forEach(id=>{const bug=state.bugs.find(b=>b.id===id);const card=node('article','review-item');card.append(node('h3','',fullTitle(bug)));const context=reportContext(bug);if(context.childNodes.length)card.append(context);const pre=combinedPreconditions(bug);if(pre)sectionReport(card,'[前置条件]',pre);sectionReport(card,'[步骤]',bug.steps);sectionReport(card,'[结果]',bug.actual);sectionReport(card,'[期望]',bug.expected);const atts=node('div','review-attachments');const files=includedAttachments(bug);atts.append(node('strong','',files.length+' 个附件'));files.forEach(a=>{const b=button(a.name,'text-button',()=>showAttachment(bug,a),'clip');atts.append(b);});card.append(atts);list.append(card);});$('reviewDialog').showModal();}catch(e){toast(errorMessage(e),true);}}
async function confirmReview(){if(batchBusy||state.job?.running)return;const b=$('confirmReviewButton');b.disabled=true;try{await flushSave();if(batchBusy)return;const next=await api('/api/save',{bugs:reviewSnapshots.map(snapshot=>({id:snapshot.id,reviewed:true,review_token:snapshot.review_token}))});adoptStateKeepingBugs(overlayPending(next));$('reviewDialog').close();renderChrome();renderEditor();toast('已审核 '+reviewSnapshots.length+' 条 Bug · 修改内容后会重新进入待审核。');}catch(e){$('reviewDialog').close();toast('审核未完成：'+errorMessage(e)+' 内容或公共信息可能发生变化，请重新载入审核。',true);try{await flushSave();adoptStateKeepingBugs(overlayPending(await api('/api/state')));renderChrome();renderEditor();}catch(refreshError){toast(errorMessage(refreshError)+' 编辑内容仍保留在当前窗口。',true);}}finally{b.disabled=false;}}
async function openSubmit(){if(batchBusy||state.job?.running)return;try{await flushSave();if(batchBusy)return;if(state.demo){toast('示例数据不能提交。请扫描你的实际 Bug 文件夹。',true);return;}if(!state.connection?.connected){openConnection();toast('先连接公司禅道，再提交已审核的 Bug。');return;}const selected=selectedBugs();const eligible=selected.filter(b=>complete(b)&&b.reviewed&&!locked(b));if(!eligible.length){toast('选中的 Bug 需要补齐并审核后才能提交。',true);return;}const blocked=selected.filter(b=>!eligible.includes(b));if(blocked.some(b=>['uncertain','partial'].includes(b.status)||b.remote_id&&b.status!=='submitted')){toast('选中条目包含需要核对的提交，请先核对或取消勾选。',true);return;}if(blocked.some(b=>!['submitted'].includes(b.status))){toast('还有 '+blocked.length+' 条选中的 Bug 未补齐或未审核，请先处理或取消勾选。',true);return;}if(!state.connection.first_verified&&eligible.length>1){toast('首次连接需先试提 1 条。请只勾选一条已审核 Bug，确认创建和附件上传成功后再批量提交。',true);return;}submitIds=eligible.map(b=>b.id);$('submitIntro').textContent=(state.connection.first_verified?'即将提交 '+eligible.length+' 条已审核 Bug。':'首次提交验证：本次只提交 1 条。请在完成后打开禅道确认内容与附件。')+(state.connection.url?'\n目标：'+state.connection.url:'');const list=$('submitItems');list.replaceChildren();eligible.forEach(b=>{const row=node('div','submit-summary-item');row.append(icon('check'),node('span','',fullTitle(b)+' · '+includedAttachments(b).length+' 个附件'));list.append(row);});$('submitDialog').showModal();}catch(e){toast(errorMessage(e),true);}}
async function confirmSubmit(){if(batchBusy||state.job?.running)return;const btn=$('confirmSubmitButton');btn.disabled=true;try{await flushSave();await api('/api/submit',{ids:submitIds});$('submitDialog').close();$('jobPanel').hidden=false;state.job={running:true,total:submitIds.length,done:0,results:[]};renderChrome();renderEditor();pollJob();}catch(e){toast(errorMessage(e),true);}finally{btn.disabled=false;}}
function renderJob(job){if(!job)return;$('jobPanel').hidden=!(job.running||job.results?.length);$('jobTitle').textContent=job.running?'正在提交 · '+job.done+' / '+job.total:job.cancel_requested?'已停止后续提交':'本次提交完成 · '+job.done+' / '+job.total;$('jobProgress').style.width=(job.total?Math.min(100,job.done/job.total*100):0)+'%';$('jobDetail').textContent=job.running?(job.cancel_requested?'正在完成当前请求，然后停止后续条目。':'正在处理：'+(job.current_title||'准备中…')):'请打开禅道核对提交结果。附件待补或结果不明确的条目需要手动处理。';$('cancelJobButton').hidden=!job.running;$('cancelJobButton').disabled=!!job.cancel_requested;$('cancelJobButton').textContent=job.cancel_requested?'已请求停止':'停止后续提交';$('hideJobButton').hidden=job.running;const list=$('jobResults');list.replaceChildren();(job.results||[]).forEach(r=>{const bug=state.bugs.find(b=>b.id===r.id),row=node('div','job-result');row.append(statusBadge(r),node('span','',(bug?.title||'Bug')+(r.error?' · '+r.error:'')));if(r.remote_url)row.append(safeLink(r.remote_url,'#'+(r.remote_id||'查看'),'text-button'));list.append(row);});}
async function pollJob(){clearTimeout(pollTimer);try{const job=await api('/api/job');state.job=job;renderJob(job);if(job.running){renderChrome();pollTimer=setTimeout(pollJob,1100);}else{await replaceState(await api('/api/state'));renderJob(state.job||job);toast(job.cancel_requested?'后续提交已停止，当前请求的结果已记录。':'提交任务已完成，请查看结果。');}}catch(e){toast(errorMessage(e),true);pollTimer=setTimeout(pollJob,4000);}}
async function cancelJob(){try{await api('/api/cancel-submit',{});state.job.cancel_requested=true;renderJob(state.job);toast('已请求停止 · 正在发送的这条请求会先完成。');}catch(e){toast(errorMessage(e),true);}}
function fieldForSetting(key,label,help,values){const wrap=node('label','field');wrap.append(node('span','',label));let input;if(values)input=makeSelect(values,settingsDraft[key]||'');else{input=node(['preconditions','steps_template'].includes(key)?'textarea':'input');if(input.tagName==='INPUT')input.type='text';else input.rows=3;input.value=Array.isArray(settingsDraft[key])?settingsDraft[key].join(','):settingsDraft[key]||'';}if(key==='feedbackBy')input.maxLength=100;input.dataset.setting=key;input.addEventListener('input',()=>{settingsDraft[key]=key==='openedBuild'?input.value.split(/[,，]/).map(v=>v.trim()).filter(Boolean):input.value;});input.addEventListener('change',()=>{settingsDraft[key]=key==='openedBuild'?input.value.split(/[,，]/).map(v=>v.trim()).filter(Boolean):input.value;});wrap.append(input);if(help)wrap.append(node('small','',help));return wrap;}
function closeChoice(){activeChoice?.close();}
function choiceSearchText(item){return ['label','value','name','account','realname','pinyin','abbr','search','searchKey','searchKeys','searchText','keys'].flatMap(key=>Array.isArray(item[key])?item[key]:[item[key]]).filter(value=>typeof value==='string'||typeof value==='number').join(' ').normalize('NFKC').toLocaleLowerCase();}
function searchableSetting(key,nameKey,label,choices){
  const multiple=key==='openedBuild',id='choice-'+(++choiceSerial),wrap=node('div','field choice-field'),heading=node('span','',label);
  heading.id=id+'-label';wrap.append(heading);
  const items=choices.filter(item=>item.value!==undefined&&item.value!==null&&String(item.value)!=='').map(item=>({...item,value:String(item.value),label:String(item.label??item.name??item.value),search:choiceSearchText(item)}));
  const control=node('div','choice-control'+(multiple?' choice-multiple':'')),chips=node('div','choice-chips'),entry=node('div','choice-entry'),input=node('input','choice-input');
  input.type='text';input.id=id;input.dataset.setting=key;input.autocomplete='off';input.spellcheck=false;input.setAttribute('role','combobox');input.setAttribute('aria-labelledby',heading.id);input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-haspopup','listbox');input.setAttribute('aria-expanded','false');input.setAttribute('aria-controls',id+'-list');
  const clear=button('','choice-clear',()=>{commit([]);input.focus();},'close');clear.setAttribute('aria-label','清空'+label);
  const toggle=button('','choice-toggle',()=>{if(activeChoice?.input===input)close();else{input.focus({preventScroll:true});open();}},'chevron');toggle.setAttribute('aria-label','展开'+label+'选项');
  entry.append(input,clear,toggle);control.append(chips,entry);wrap.append(control);
  const popup=node('div','choice-popup'),list=node('div','choice-options'),status=node('div','choice-result-count');
  popup.setAttribute('popover','manual');list.id=id+'-list';list.setAttribute('role','listbox');list.setAttribute('aria-labelledby',heading.id);if(multiple)list.setAttribute('aria-multiselectable','true');status.setAttribute('role','status');status.setAttribute('aria-live','polite');popup.append(list,status);
  const actions=node('div','choice-popup-actions'),selectAll=button('选择当前结果','text-button',()=>{commit([...new Set([...selected(),...filtered.map(item=>item.value)])]);input.focus({preventScroll:true});}),clearAll=button('清空已选','text-button',()=>{commit([]);input.focus({preventScroll:true});});
  if(multiple){actions.append(selectAll,clearAll);popup.append(actions);wrap.append(node('small','','点击勾选，可多选；输入版本名称可快速查找。'));}
  const unmatched=key==='probability'?node('small','','当前保存的概率未匹配，请从菜单重新选择。'):null;if(unmatched)wrap.append(unmatched);
  let filtered=[],activeIndex=-1,composing=false,opened=false,query='';
  const selected=()=>multiple?(Array.isArray(settingsDraft[key])?settingsDraft[key].map(String):[]):settingsDraft[key]!==undefined&&settingsDraft[key]!==null&&String(settingsDraft[key])!==''?[String(settingsDraft[key])]:[];
  const savedLabel=value=>items.find(item=>item.value===value)?.label||(!multiple&&nameKey&&settingsDraft[nameKey]?String(settingsDraft[nameKey]):multiple&&selected().length===1&&settingsDraft[nameKey]?String(settingsDraft[nameKey]):value);
  function sync(){
    const values=selected();chips.replaceChildren();chips.hidden=!multiple||!values.length;clear.hidden=multiple||!values.length;
    if(multiple)values.forEach(value=>{const chip=node('span','choice-chip'),text=node('span','choice-chip-label',savedLabel(value)),remove=button('','choice-chip-remove',()=>{commit(selected().filter(v=>v!==value));},'close');text.title=text.textContent;remove.setAttribute('aria-label','移除 '+text.textContent);chip.append(text,remove);chips.append(chip);});
    input.placeholder=opened?'输入关键词搜索…':multiple?(values.length?'继续选择版本…':'请选择，可输入搜索…'):'请选择，可输入搜索…';
    if(!opened)input.value=multiple?'':values.length?savedLabel(values[0]):'';control.classList.toggle('has-value',values.length>0);if(unmatched)unmatched.hidden=!values.length||items.some(item=>item.value===values[0]);
  }
  function setActive(index){
    activeIndex=filtered.length?Math.min(Math.max(index,0),filtered.length-1):-1;
    [...list.children].forEach((row,i)=>row.classList.toggle('keyboard-active',i===activeIndex));
    if(activeIndex<0)input.removeAttribute('aria-activedescendant');else{const row=list.children[activeIndex];input.setAttribute('aria-activedescendant',row.id);if(row.offsetTop<list.scrollTop)list.scrollTop=row.offsetTop;else if(row.offsetTop+row.offsetHeight>list.scrollTop+list.clientHeight)list.scrollTop=row.offsetTop+row.offsetHeight-list.clientHeight;}
  }
  function renderOptions(reset=false){
    const terms=query.trim().normalize('NFKC').toLocaleLowerCase().split(/\s+/).filter(Boolean);filtered=items.filter(item=>terms.every(term=>item.search.includes(term)));const values=selected();list.replaceChildren();
    filtered.forEach((item,i)=>{const row=button('','choice-option',()=>{if(multiple){const next=selected();commit(next.includes(item.value)?next.filter(v=>v!==item.value):[...next,item.value]);input.focus({preventScroll:true});}else commit([item.value]);});row.id=id+'-option-'+i;row.dataset.choiceValue=item.value;row.setAttribute('role','option');row.setAttribute('aria-selected',String(values.includes(item.value)));row.tabIndex=-1;row.title=item.label;row.classList.toggle('selected',values.includes(item.value));
      const mark=node('span',multiple?'choice-checkbox':'choice-selected-mark');mark.setAttribute('aria-hidden','true');if(values.includes(item.value))mark.append(icon('check'));row.append(mark,node('span','choice-option-label',item.label));if(key==='assignedTo'&&item.value!==item.label)row.append(node('small','choice-option-account',String(item.account||item.value)));row.addEventListener('pointerdown',e=>e.preventDefault());list.append(row);});
    if(!filtered.length)list.append(node('div','choice-empty','没有找到匹配项，请换个关键词。'));
    status.textContent=filtered.length+' 个选项'+(multiple?' · 已选 '+values.length+' 个版本':'');selectAll.disabled=!filtered.length;clearAll.disabled=!values.length;
    if(reset)activeIndex=filtered.findIndex(item=>values.includes(item.value));setActive(activeIndex<0?0:activeIndex);position();
  }
  function position(){
    if(!opened)return;if(!control.isConnected||!$('settingsDialog').open){close();return;}
    const rect=control.getBoundingClientRect(),body=$('settingsForm').querySelector('.modal-body').getBoundingClientRect(),view=window.visualViewport,leftEdge=view?.offsetLeft||0,topEdge=view?.offsetTop||0,width=view?.width||innerWidth,height=view?.height||innerHeight;
    if(rect.bottom<body.top||rect.top>body.bottom){close();return;}
    const below=topEdge+height-rect.bottom-10,above=rect.top-topEdge-10,up=below<180&&above>below,available=Math.max(72,up?above:below),popupHeight=Math.min(330,available,height-20),popupWidth=Math.min(Math.max(rect.width,240),width-20);
    popup.style.width=popupWidth+'px';popup.style.maxHeight=popupHeight+'px';popup.style.left=Math.max(leftEdge+10,Math.min(rect.left,leftEdge+width-popupWidth-10))+'px';const actualHeight=popup.getBoundingClientRect().height;popup.style.top=(up?Math.max(topEdge+10,rect.top-actualHeight-5):Math.max(topEdge+10,Math.min(rect.bottom+5,topEdge+height-actualHeight-10)))+'px';popup.classList.toggle('opens-up',up);
  }
  function open(){
    if(opened||!$('settingsDialog').open)return;closeChoice();opened=true;query='';input.value='';input.setAttribute('aria-expanded','true');control.classList.add('is-open');$('settingsDialog').append(popup);popup.hidden=false;
    if(typeof popup.showPopover==='function')popup.showPopover();else popup.dataset.fallbackOpen='';activeChoice={input,control,popup,close,position};sync();renderOptions(true);
  }
  function close(){
    if(!opened)return;opened=false;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');control.classList.remove('is-open');if(typeof popup.hidePopover==='function'&&popup.matches(':popover-open'))popup.hidePopover();popup.remove();if(activeChoice?.input===input)activeChoice=null;sync();
  }
  function commit(values){
    const next=[...new Set(values.map(String))],before=JSON.stringify(selected()),labels=next.map(savedLabel);settingsDraft[key]=multiple?next:(next[0]||'');if(nameKey)settingsDraft[nameKey]=labels.join('、');
    if(multiple){sync();if(opened)renderOptions();}else close();
    if(before!==JSON.stringify(next)&&['product','project','execution'].includes(key)){
      if(key==='product'){Object.assign(settingsDraft,{project:'',project_name:'',execution:'',execution_name:'',module:'0',module_name:'',openedBuild:[],build_name:''});options={...options,projects:[],executions:[],modules:[],builds:[],probabilities:[]};}
      if(key==='project'){Object.assign(settingsDraft,{execution:'',execution_name:''});options={...options,executions:[],builds:[],probabilities:[]};}
      if(key==='execution')options={...options,builds:[],probabilities:[]};
      menuContext='';renderSettingsFields();loadOptions(true);
    }
  }
  function filterInput(){const value=input.value;if(!opened)open();input.value=value;query=value;renderOptions(true);}
  input.addEventListener('focus',open);input.addEventListener('click',open);input.addEventListener('paste',()=>{if(!opened)open();});input.addEventListener('compositionstart',()=>{composing=true;});input.addEventListener('compositionend',()=>{composing=false;filterInput();});input.addEventListener('input',e=>{if(composing||e.isComposing)return;filterInput();});
  input.addEventListener('keydown',e=>{if(!opened&&!composing&&!e.ctrlKey&&!e.metaKey&&!e.altKey&&(e.key.length===1||e.key==='Process'))open();if(composing||e.isComposing||e.keyCode===229)return;if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();if(!opened)open();else setActive(activeIndex+(e.key==='ArrowDown'?1:-1));}else if(e.key==='Enter'){e.preventDefault();if(!opened)open();else if(filtered[activeIndex]){const item=filtered[activeIndex],values=selected();commit(multiple?(values.includes(item.value)?values.filter(v=>v!==item.value):[...values,item.value]):[item.value]);}}else if(e.key==='Escape'&&opened){e.preventDefault();e.stopPropagation();close();}else if(e.key==='Tab')close();});
  sync();return wrap;
}
function remoteSetting(key,nameKey,label,optionKey){
  const choices=options[optionKey]||[];
  if(!choices.length)return fieldForSetting(nameKey||key,label,key==='probability'?'连接后自动读取公司的概率选项。':'连接后可读取菜单；需要时可在下面填写实际编号。');
  return searchableSetting(key,nameKey,label,choices);
}
function normalizeProbabilityDraft(){
  const value=String(settingsDraft.probability??'');if(!value||!options.probabilities?.length||options.probabilities.some(item=>String(item.value)===value))return;
  const matches=options.probabilities.filter(item=>String(item.label)===value);if(matches.length===1)settingsDraft.probability=String(matches[0].value);
}
function renderSettingsFields(){
  if(settingsComposing){menusRenderPending=true;return;}menusRenderPending=false;
  const fields=$('settingsFields'),body=$('settingsForm').querySelector('.modal-body'),scroll=body.scrollTop,focused=document.activeElement,focusKey=fields.contains(focused)?focused.dataset.setting:null,caret=focused?.selectionStart,caretEnd=focused?.selectionEnd,choiceQuery=activeChoice?.input===focused?focused.value:null;
  closeChoice();normalizeProbabilityDraft();fields.replaceChildren();
  const definitions=[['product','product_name','所属产品','products'],['project','project_name','所属项目','projects'],['execution','execution_name','所属执行','executions'],['openedBuild','build_name','影响版本','builds'],['assignedTo','assignee_name','当前指派','users'],['module','module_name','所属模块','modules']];definitions.forEach(args=>fields.append(remoteSetting(...args)));
  fields.append(fieldForSetting('feedbackBy','反馈者','发现或反馈该问题的人，例如你的姓名；填一次，整批复用。'),fieldForSetting('type','默认 Bug 类型','',TYPES),fieldForSetting('severity','默认严重程度','',SEVERITIES),fieldForSetting('pri','默认优先级','',priorityItems()),remoteSetting('probability',null,'发生概率','probabilities'),fieldForSetting('os','操作系统（选填）','按公司禅道字段值填写；可留空。'),fieldForSetting('title_prefix','标题公共前缀（选填）','例如：【1.0需求版本】。提交预览会显示完整标题。'));
  if(menuBusy||menuWarnings.length){const notice=node('div','settings-menu-status'+(menuWarnings.length?' warning':''),menuBusy?'正在读取公司的菜单…':menuWarnings.join('；'));notice.setAttribute('role','status');fields.append(notice);}
  if(!menuBusy&&options.probability_diagnostic)fields.append(probabilityDiagnosticControl());
  const advanced=$('advancedFields');advanced.replaceChildren();definitions.filter(([, , ,optionKey])=>!options[optionKey]?.length).forEach(([key,nameKey,label])=>{advanced.append(fieldForSetting(key,key==='assignedTo'?'指派账号':label.replace(/^所属/,'')+'编号',key==='openedBuild'?'多个版本编号用逗号分隔。':key==='assignedTo'?'填写禅道登录账号。':'请使用公司禅道的实际编号。'),fieldForSetting(nameKey,label.replace(/^所属/,'')+'名称','用于本地显示。'));});
  advanced.append(fieldForSetting('preconditions','公共前置条件（选填）','每条 Bug 都会包含公共前置条件，并合并本条额外条件。'),fieldForSetting('steps_template','公共步骤模板（选填）','编辑 Bug 时可显式填入，再按实际操作修改。'));renderProfiles();$('loadOptionsButton').disabled=menuBusy||!state.connection?.connected;
  if(focusKey&&$('settingsDialog').open){const restored=[...fields.querySelectorAll('[data-setting]')].find(el=>el.dataset.setting===focusKey);if(restored){restored.focus({preventScroll:true});if(choiceQuery!==null&&restored.classList.contains('choice-input')){restored.value=choiceQuery;restored.dispatchEvent(new Event('input'));}else closeChoice();if(caret!==null&&caret!==undefined&&typeof restored.setSelectionRange==='function')try{restored.setSelectionRange(caret,caretEnd??caret);}catch{}}}body.scrollTop=scroll;
}
function probabilityDiagnosticControl(){
  const wrap=node('div','settings-diagnostic');
  const copy=button('复制字段诊断','button secondary',async()=>{
    if(menuBusy||menuContext!==menuContextKey(settingsDraft)){toast('菜单正在更新，请加载完成后再复制。',true);return;}
    const diagnostic=structuredClone(options.probability_diagnostic);
    if(!diagnostic)return;
    diagnostic.app_version=$('versionLabel').textContent.match(/^v([\d.]+)/)?.[1]||'';
    const text=JSON.stringify(diagnostic,null,2);
    try{await navigator.clipboard.writeText(text);toast('字段诊断已复制，可粘贴发送给我排查。');}
    catch{
      let output=wrap.querySelector('textarea');
      if(!output){output=node('textarea','diagnostic-text');output.readOnly=true;output.setAttribute('aria-label','字段诊断内容');output.rows=7;wrap.append(output);}
      output.value=text;output.focus();output.select();toast('浏览器未允许自动复制，请复制下方已选中的内容。',true);
    }
  },'copy');
  wrap.append(copy,node('small','','概率仍未读取时，可复制诊断信息发回排查。'));
  return wrap;
}
function renderProfiles(){const select=$('profileSelect');select.replaceChildren();const empty=node('option','','选择已有配置');empty.value='';select.append(empty);(state.profiles||[]).forEach((p,i)=>{const opt=node('option','',p.name||'常用配置 '+(i+1));opt.value=p.id||String(i);select.append(opt);});select.value='';}
function menuContextKey(settings){return JSON.stringify([state.connection?.url||'',...['product','project','execution'].map(key=>String(settings[key]??''))]);}
function restoreCachedMenus(next){
  const cached=next.options||{},context=next.options_context||{};if(!next.connection?.connected){options={};menuContext='';menuWarnings=[];return;}
  const matches=['product','project','execution'].every(key=>String(context[key]??'')===String(next.settings[key]??''));options=matches?{...cached}:{products:cached.products||[],users:cached.users||[]};menuContext=matches?menuContextKey(next.settings):'';menuWarnings=matches?(cached.warnings||[]).map(String):[];
}
async function openSettings(){if(batchBusy||state.job?.running)return;try{await flushSave();if(batchBusy)return;settingsDraft=structuredClone(state.settings);if(menuContext!==menuContextKey(settingsDraft)){options={products:options.products||[],users:options.users||[]};menuWarnings=[];}renderSettingsFields();$('profileName').value='';$('settingsDialog').showModal();if(state.connection?.connected&&menuContext!==menuContextKey(settingsDraft))await loadOptions(true,{quiet:true});}catch(e){toast(errorMessage(e),true);}}
async function saveSettings(e){e?.preventDefault();if(batchBusy||state.job?.running)return;const next={...settingsDraft};next.openedBuild=Array.isArray(next.openedBuild)?next.openedBuild:[];const changed=JSON.stringify(next)!==JSON.stringify(state.settings);if(changed){state.settings=next;dirtySettings=next;state.bugs.filter(b=>!locked(b)).forEach(b=>localEdit(b,{reviewed:false},false));}try{await flushSave();$('settingsDialog').close();renderEditor();toast(changed?'公共信息已保存 · 请重新审核受影响的 Bug。':'公共信息已保存');}catch(err){toast(errorMessage(err),true);}}
async function loadOptions(inSettings=false,{quiet=false}={}){
  if(!state.connection?.connected){if(!quiet)toast('请先连接禅道。',true);return;}const btn=$('loadOptionsButton'),serial=++menuSerial,draft=inSettings?settingsDraft:state.settings,context=menuContextKey(draft),request=Object.fromEntries(['product','project','execution'].map(key=>[key,String(draft[key]??'')]));menuBusy=true;btn.disabled=true;if(inSettings&&$('settingsDialog').open){let notice=$('settingsFields').querySelector('.settings-menu-status');if(!notice){notice=node('div','settings-menu-status');notice.setAttribute('role','status');$('settingsFields').append(notice);}notice.className='settings-menu-status';notice.textContent='正在读取公司的菜单…';}
  const current=()=>serial===menuSerial&&state.connection?.connected&&context===menuContextKey(inSettings?settingsDraft:state.settings);
  try{const result=await api('/api/options',request);if(!current())return;options={products:options.products||[],users:options.users||[],...result};menuContext=context;menuWarnings=(result.warnings||[]).map(String);menuBusy=false;if(inSettings&&$('settingsDialog').open)renderSettingsFields();else if(!$('editorPanel').contains(document.activeElement))renderEditor();if(!quiet)toast(menuWarnings.length?'菜单已读取，请检查未加载的选项。':'禅道菜单已更新',!!menuWarnings.length);return result;}
  catch(e){if(!current())return;menuWarnings=[errorMessage(e)+'，可重新加载菜单。'];menuBusy=false;if(inSettings&&$('settingsDialog').open)renderSettingsFields();if(!quiet)toast(menuWarnings[0],true);}
  finally{if(serial===menuSerial){menuBusy=false;btn.disabled=!state.connection?.connected;}}
}
async function saveProfile(){if(batchBusy||state.job?.running)return;const name=$('profileName').value.trim();if(!name){toast('给这个配置起个名字。',true);$('profileName').focus();return;}const profiles=structuredClone(state.profiles||[]);const existing=profiles.find(p=>p.name===name),id=existing?.id||'profile-'+Date.now();const item={id,name,settings:structuredClone(settingsDraft)};if(existing)profiles[profiles.indexOf(existing)]=item;else profiles.push(item);state.profiles=profiles;dirtyProfiles=profiles;try{await flushSave();renderProfiles();$('profileName').value='';toast('常用配置已保存：'+name);}catch(e){toast(errorMessage(e),true);}}
function applyProfile(){const key=$('profileSelect').value;if(!key)return;const profile=(state.profiles||[]).find((p,i)=>(p.id||String(i))===key);if(!profile)return;settingsDraft={...state.settings,...structuredClone(profile.settings||{})};dirtyActiveProfile=profile.id||key;const reload=menuContext!==menuContextKey(settingsDraft);if(reload){options={products:options.products||[],users:options.users||[]};menuWarnings=[];}renderSettingsFields();$('profileName').value=profile.name||'';toast('已载入配置，点击“保存公共信息”后应用。');if(reload&&state.connection?.connected)loadOptions(true,{quiet:true});}
function openConnection(){if(batchBusy||state.job?.running)return;const connected=state.connection?.connected;$('connectDialogTitle').textContent=connected?'禅道连接已建立':'提交前，连接禅道';$('zentaoUrl').value=state.connection?.url||state.settings.zentao_url||'';$('zentaoUrl').disabled=connected;$('credentialFields').hidden=connected;$('zentaoAccount').required=!connected;$('zentaoPassword').required=!connected;$('disconnectButton').hidden=!connected;$('connectSubmitButton').hidden=connected;$('connectedInfo').hidden=!connected;$('connectedInfo').textContent=connected?(state.connection.message||'连接成功')+'\n'+(state.connection.first_verified?'这台禅道已经完成创建与附件验证，可批量提交。':'首次提交请只选择 1 条，以验证实际创建与附件上传。'):'';$('connectError').hidden=true;$('connectionDialog').showModal();}
async function connect(e){e.preventDefault();const btn=$('connectSubmitButton');btn.disabled=true;btn.textContent='正在连接…';$('connectError').hidden=true;try{await flushSave();const url=$('zentaoUrl').value.trim(),result=await api('/api/connect',{url,account:$('zentaoAccount').value.trim(),password:$('zentaoPassword').value});$('zentaoPassword').value='';++menuSerial;menuBusy=false;menuContext='';menuWarnings=[];options={...(result.options||{})};adoptStateKeepingBugs(await api('/api/state'));renderChrome();renderEditor();$('connectionDialog').close();toast(result.message||'禅道已连接，现在可以设置公共信息。');await loadOptions(false,{quiet:true});if(!state.settings.product||!state.settings.openedBuild?.length)await openSettings();}catch(error){$('connectError').textContent=errorMessage(error);$('connectError').hidden=false;}finally{btn.disabled=false;btn.textContent='连接并读取菜单';}}
async function disconnect(){try{await api('/api/disconnect',{});++menuSerial;menuBusy=false;menuContext='';menuWarnings=[];closeChoice();state.connection={connected:false,first_verified:false};options={};$('zentaoPassword').value='';$('connectionDialog').close();renderChrome();toast('禅道已断开，草稿仍保存在本机。');}catch(e){toast(errorMessage(e),true);}}
async function exportBatch(format){if(batchBusy)return;try{await flushSave();const result=await api('/api/export',{format});const area=$('exportResult');area.hidden=false;area.replaceChildren(node('div','','已导出到：'+result.path));const a=node('a','text-button','下载 '+result.filename);a.href=result.url;a.download=result.filename;area.append(a);a.click();toast('导出完成 · '+result.filename);}catch(e){toast(errorMessage(e),true);}}
async function importBackup(file){if(!file||batchBusy||scanBusy||state.job?.running)return;try{const raw=await file.text(),data=JSON.parse(raw);if(!confirm('导入备份将切换当前批次。当前编辑会先保存。导入后，请重新扫描原始目录，核对附件是否还在。'))return;if(await switchBatch(()=>api('/api/import',{data}))){$('exportDialog').close();toast('备份已导入，请重新扫描原始目录以核对附件。');}}catch(e){toast(e instanceof SyntaxError?'这个文件不是有效的 JSON 备份。':errorMessage(e),true);}finally{$('importFile').value='';}}
function openResolve(bug){let dialog=$('resolveDialog');if(!dialog){dialog=node('dialog','modal');dialog.id='resolveDialog';document.body.append(dialog);}dialog.replaceChildren();const head=node('div','modal-header');head.append(node('h2','','记录禅道核对结果'),button('','icon-button',()=>dialog.close(),'close'));const body=node('div','modal-body');body.append(node('div','notice warning','请先在公司禅道按标题、提交人和时间查找。只有亲自确认后，才能记录此处结果。'));if(bug.remote_url)body.append(safeLink(bug.remote_url,'打开禅道核对','text-button'));const form=node('form'),created=node('label','field');created.append(node('span','','核对结果'));const canReset=bug.status==='uncertain'&&!bug.remote_id;const select=makeSelect([['created','Bug 已存在，且附件已齐全'],...(canReset?[['not_created','已确认 Bug 没有创建，恢复草稿']]:[])],'created');created.append(select);const idField=node('label','field');idField.append(node('span','','已创建的 Bug 编号'));const id=node('input');id.type='number';id.min='1';id.value=bug.remote_id||'';id.required=true;id.placeholder='例如 12345';idField.append(id);const checkRow=node('label','select-all');checkRow.style.fontSize='11px';checkRow.style.lineHeight='1.9';checkRow.style.marginTop='18px';const check=node('input');check.type='checkbox';check.required=true;const copy=node('span','','我已在禅道核对，Bug 内容与附件均正确。');checkRow.append(check,copy);select.addEventListener('change',()=>{idField.hidden=select.value!=='created';id.required=select.value==='created';check.checked=false;copy.textContent=select.value==='created'?'我已在禅道核对，Bug 内容与附件均正确。':'我已查找并确认没有创建该 Bug，允许再次提交。';});form.append(created,idField,checkRow);body.append(form);const foot=node('div','modal-footer');const commit=button('保存核对结果','button primary',()=>form.requestSubmit());foot.append(button('返回','button secondary',()=>dialog.close()),commit);form.addEventListener('submit',async e=>{e.preventDefault();commit.disabled=true;try{await flushSave();const next=await api('/api/resolve-submission',{id:bug.id,resolution:select.value,remote_id:select.value==='created'?Number(id.value):undefined,confirmed:true});await replaceState(next);dialog.close();toast(select.value==='created'?'已记录：Bug 和附件确认完成。':'已恢复草稿，请重新审核后提交。');}catch(e){toast(errorMessage(e),true);}finally{commit.disabled=false;}});dialog.append(head,body,foot);dialog.showModal();}
async function shutdown(){if(batchBusy)return;if(state.job?.running){toast('正在提交，请先等任务完成，或停止后续提交。',true);return;}if(!confirm('所有编辑会先保存，然后关闭本地工具服务。确定退出吗？'))return;try{await flushSave();await api('/api/shutdown',{});shuttingDown=true;clearInterval(heartbeatTimer);clearTimeout(pollTimer);document.body.replaceChildren();const content=node('div','shut-message');content.append(icon('check'),node('h1','','已保存，今天辛苦了。'),node('p','','BugDesk 已关闭。你可以关闭这个浏览器标签页。'));document.body.append(content);}catch(e){toast(errorMessage(e),true);}}
function closeHeaderPanels(except=null){
  for(const id of ['folderPicker','moreMenu','bugSettings']){const panel=$(id);if(panel&&panel!==except)panel.open=false;}
}
function installThemeToggle(){
  if(!window.bugDeskAppearance)return;
  const control=$('themeToggle');if(!control)return;
  function refresh(){
    const dark=document.documentElement.dataset.theme==='dark',label=dark?'切换到浅色模式':'切换到深色模式';
    control.replaceChildren(icon(dark?'sun':'moon'));control.title=label;control.setAttribute('aria-label',label);
  }
  control.addEventListener('click',()=>window.bugDeskAppearance.toggle());
  window.addEventListener('bugdesk-theme-change',refresh);refresh();
}
function bindHeaderPanels(){
  document.querySelectorAll('.header-popover').forEach(panel=>panel.addEventListener('toggle',()=>{if(panel.open)closeHeaderPanels(panel);}));
  document.addEventListener('click',event=>{
    if(!event.target.closest('.header-popover'))closeHeaderPanels();
    else if(event.target.closest('.more-popup button'))closeHeaderPanels();
  });
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){
    const opened=document.querySelector('.header-popover[open]');
    if(opened){event.preventDefault();closeHeaderPanels();opened.querySelector('summary').focus();}
  }});
}
function bindEvents(){hydrateIcons();installThemeToggle();bindHeaderPanels();$('workBuddyGuideButton').addEventListener('click',()=>workBuddyOpenHelp());$('browseButton').addEventListener('click',pickAndScan);$('emptyBrowseButton').addEventListener('click',pickAndScan);$('scanButton').addEventListener('click',scanFolder);$('folderInput').addEventListener('keydown',e=>{if(e.key==='Enter')scanFolder();});$('demoButton').addEventListener('click',loadDemo);$('settingsButton').addEventListener('click',openSettings);$('connectionButton').addEventListener('click',openConnection);$('settingsForm').addEventListener('submit',saveSettings);$('connectionForm').addEventListener('submit',connect);$('disconnectButton').addEventListener('click',disconnect);$('loadOptionsButton').addEventListener('click',()=>loadOptions(true));$('saveProfileButton').addEventListener('click',saveProfile);$('profileSelect').addEventListener('change',applyProfile);$('searchInput').addEventListener('input',e=>{search=e.target.value.trim().toLowerCase();renderChrome();});$('filterBar').addEventListener('click',e=>{const b=e.target.closest('[data-filter]');if(!b)return;filter=b.dataset.filter;$('filterBar').querySelectorAll('.filter').forEach(el=>el.classList.toggle('active',el===b));renderChrome();});$('selectAll').addEventListener('change',e=>{const selected=e.target.checked;shownBugs().forEach(b=>localEdit(b,{selected},false));});$('reviewSelectedButton').addEventListener('click',()=>openReview(selectedBugs().map(b=>b.id)));$('confirmReviewButton').addEventListener('click',confirmReview);$('submitButton').addEventListener('click',openSubmit);$('confirmSubmitButton').addEventListener('click',confirmSubmit);$('cancelJobButton').addEventListener('click',cancelJob);$('hideJobButton').addEventListener('click',()=>$('jobPanel').hidden=true);$('exportButton').addEventListener('click',async()=>{try{await flushSave();$('exportResult').hidden=true;$('exportDialog').showModal();}catch(e){toast(errorMessage(e),true);}});document.querySelectorAll('[data-export]').forEach(b=>b.addEventListener('click',()=>exportBatch(b.dataset.export)));$('importButton').addEventListener('click',()=>$('importFile').click());$('importFile').addEventListener('change',e=>importBackup(e.target.files?.[0]));$('helpButton').addEventListener('click',()=>$('helpDialog').showModal());$('shutdownButton').addEventListener('click',shutdown);$('openBatchButton').addEventListener('click',async()=>{try{await api('/api/open-folder',{});}catch(e){toast(errorMessage(e),true);}});$('workbenchButton').addEventListener('click',()=>{$('searchInput').focus({preventScroll:true});});document.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>$(b.dataset.close).close()));document.querySelectorAll('dialog').forEach(d=>{d.addEventListener('click',e=>{if(e.target!==d)return;const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();});});$('previewDialog').addEventListener('close',()=>{$('previewContent').querySelectorAll('video,audio').forEach(m=>m.pause());});document.addEventListener('keydown',async e=>{if(e.ctrlKey&&e.key.toLowerCase()==='s'){e.preventDefault();try{await flushSave();toast('已保存全部修改');}catch(error){toast(errorMessage(error),true);}}if(e.ctrlKey&&e.key==='Enter'&&!document.querySelector('dialog[open]')){e.preventDefault();if(currentId)openReview([currentId]);}if(e.altKey&&['ArrowUp','ArrowDown'].includes(e.key)&&!document.querySelector('dialog[open]')){e.preventDefault();adjacent(e.key==='ArrowUp'?-1:1);}});window.addEventListener('beforeunload',e=>{if(shuttingDown)return;if(hasPendingSave()){flushSave().catch(()=>{});e.preventDefault();e.returnValue='还有编辑正在保存，请稍候。';}});document.addEventListener('visibilitychange',()=>{if(document.hidden&&(dirtyBugs.size||dirtySettings||dirtyProfiles))flushSave().catch(()=>{});});}
function bindChoiceEvents(){
  document.addEventListener('pointerdown',e=>{if(activeChoice&&!activeChoice.control.contains(e.target)&&!activeChoice.popup.contains(e.target))closeChoice();},true);
  document.addEventListener('focusin',e=>{if(activeChoice&&!activeChoice.control.contains(e.target)&&!activeChoice.popup.contains(e.target))closeChoice();});
  document.addEventListener('scroll',e=>{if(activeChoice&&!activeChoice.popup.contains(e.target))activeChoice.position();},true);window.addEventListener('resize',()=>activeChoice?.position());window.visualViewport?.addEventListener('resize',()=>activeChoice?.position());window.visualViewport?.addEventListener('scroll',()=>activeChoice?.position());
  $('settingsDialog').addEventListener('close',()=>{closeChoice();settingsComposing=false;++menuSerial;menuBusy=false;});$('settingsDialog').addEventListener('cancel',e=>{if(activeChoice){e.preventDefault();closeChoice();}});
  document.addEventListener('compositionstart',e=>{if($('settingsForm').contains(e.target))settingsComposing=true;});document.addEventListener('compositionend',e=>{if($('settingsForm').contains(e.target)){settingsComposing=false;if(menusRenderPending)setTimeout(()=>{if($('settingsDialog').open)renderSettingsFields();},0);}});
}
async function init(){bindEvents();installCaseImport();installWorkBuddy();bindChoiceEvents();try{const bootstrap=await api('/api/bootstrap');token=bootstrap.token;$('versionLabel').textContent='v'+(bootstrap.version||'1.0.0')+' · 本机运行';await replaceState(await api('/api/state'));renderJob(state.job);if(state.connection?.connected&&menuContext!==menuContextKey(state.settings))await loadOptions(false,{quiet:true});if(state.job?.running)pollJob();heartbeatTimer=setInterval(()=>api('/api/ping').catch(()=>{}),25000);}catch(e){$('saveStatus').textContent='本地服务未连接';toast(errorMessage(e),true);}}
function probabilityOverrideField(bug,isLocked){
  const field=node('label','field');field.append(node('span','','发生概率'));
  const select=node('select');select.setAttribute('aria-label','单独发生概率');select.dataset.override='probability';select.disabled=isLocked;
  let signature='';
  function refresh(){
    const remote=(options.probabilities||[]).filter(item=>String(item.value)!==''&&item.label);
    const choices=remote.length?remote.map(item=>[String(item.value),String(item.label)]):['必现','高','中','低'].map(label=>[label,label]);
    const current=String(bug.overrides?.probability||'');let displayed=current;
    if(current&&!choices.some(([value])=>value===current)){
      const matching=choices.filter(([,label])=>label===current);
      if(matching.length===1)displayed=matching[0][0];
      else choices.unshift([current,'已保存的单独概率（连接后核对）']);
    }
    const nextSignature=JSON.stringify([choices,current]);if(nextSignature===signature)return;signature=nextSignature;
    const replacement=makeSelect(choices,displayed,'跟随公共配置');select.replaceChildren(...replacement.childNodes);select.value=displayed;
  }
  refresh();select.addEventListener('focus',refresh);select.addEventListener('pointerdown',refresh);
  select.addEventListener('change',()=>{
    if(locked(bug))return;
    const overrides={...bug.overrides};if(select.value)overrides.probability=select.value;else delete overrides.probability;
    localEdit(bug,{overrides});
  });
  field.append(select);return field;
}
document.addEventListener('DOMContentLoaded',init,{once:true});
