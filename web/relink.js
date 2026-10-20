/* Scanning may explicitly reuse a missing folder's saved Bug; evidence is never moved. */
"use strict";

let scanRelinkChoosing = false;

function scanRelinkText(value, fallback='') {
  return value === null || value === undefined ? fallback : String(value);
}

function scanRelinkStatus(source) {
  const labels = {draft:'待补充',needs_review:'待审核',ready:'已审核',submitted:'已提交',submitting:'提交中',failed:'提交失败',uncertain:'需核对',partial:'附件待补'};
  const status = labels[source.status] || scanRelinkText(source.status,'已保存');
  return status + (source.remote_id ? ' · 禅道 #' + scanRelinkText(source.remote_id) : '');
}

/* Called inside switchBatch after its save flush. This function only previews; the caller scans. */
async function chooseScanRelinks(path) {
  if (scanRelinkChoosing) throw new Error('请先完成当前文件夹关联。');
  scanRelinkChoosing = true;
  try {
    const raw = await api('/api/scan/preview',{path});
    if (!Array.isArray(raw.targets) || !Array.isArray(raw.sources)) throw new Error('扫描预览不完整，请重新扫描。');
    const plan={...raw,targets:raw.targets.slice(0,300),sources:raw.sources.slice(0,300),
      target_count:Math.max(raw.targets.length,Number(raw.target_count)||0),
      source_count:Math.max(raw.sources.length,Number(raw.source_count)||0),
      truncated:!!raw.truncated||raw.targets.length>300||raw.sources.length>300};
    if (!plan.targets.length || !plan.sources.length) return {path};
    if (!plan.plan_id || plan.sources.some(source=>!source.source_batch_key || !source.bug_id || !source.review_token)) {
      throw new Error('旧记录的关联信息不完整，请重新扫描。');
    }
    return await scanRelinkShow(plan,path);
  } finally {
    scanRelinkChoosing = false;
  }
}

function scanRelinkShow(plan,path) {
  const previousFocus = document.activeElement;
  const sources = plan.sources;
  const assignments = new Map();
  const rows = [];
  let activeRow = -1;
  const batches = new Map();
  sources.forEach(source=>{
    if (!batches.has(source.source_batch_key)) batches.set(source.source_batch_key,scanRelinkText(source.source_root,source.source_batch_key));
  });
  const dialog = node('dialog','modal scan-relink-modal');
  dialog.id = 'scanRelinkDialog';
  dialog.setAttribute('aria-labelledby','scanRelinkTitle');
  dialog.setAttribute('aria-describedby','scanRelinkIntro');
  const header = node('div','modal-header');
  const heading = node('div');
  heading.append(node('span','eyebrow','扫描前核对'));
  const title = node('h2','','关联原来的 Bug'); title.id='scanRelinkTitle';
  heading.append(title);
  const close = button('','icon-button',()=>dialog.close(),'close');
  close.id='scanRelinkClose'; close.setAttribute('aria-label','取消扫描');
  header.append(heading,close);
  const body = node('div','modal-body scan-relink-body');
  const intro = node('p','scan-relink-intro',
    '发现 '+plan.target_count+' 个新文件夹，以及原路径已不存在的旧记录。若是改名或搬迁，可沿用旧 Bug；默认不关联，未选择的文件夹会作为新 Bug。');
  intro.id='scanRelinkIntro';
  const root = node('p','scan-relink-root','本次扫描：'+scanRelinkText(plan.root_dir,path));
  const policy = node('div','notice info scan-relink-policy');
  policy.append(node('p','','沿用会保留编辑后的标题、描述、提交编号与状态，并重新读取附件。原始证据不会被移动、改名或删除。'));
  policy.append(node('p','','一次扫描只能沿用同一个旧目录批次的记录；每条旧记录只能关联一个新文件夹。'));
  if (plan.settings_policy) policy.append(node('p','',scanRelinkText(plan.settings_policy)));
  if (plan.truncated) policy.append(node('p','scan-relink-limit',scanRelinkText(plan.notice,
    '本次最多显示 300 个新文件夹与 300 条旧记录。未显示的文件夹仍会作为新 Bug 扫描；需要沿用的记录请分批处理。为避免遗漏重复名称，本次不提供同名批量匹配。')));
  const tools = node('div','scan-relink-tools');
  const batchLabel = node('label','scan-relink-batch');
  batchLabel.append(node('span','','选择旧目录筛选记录；整个日期目录搬迁时可匹配同名记录'));
  const batchSelect = node('select'); batchSelect.id='scanRelinkBatch';
  const batchPlaceholder = node('option','','选择旧目录'); batchPlaceholder.value=''; batchSelect.append(batchPlaceholder);
  for (const [key,label] of batches) {
    const option=node('option','',label); option.value=key; option.title=label; batchSelect.append(option);
  }
  batchLabel.append(batchSelect);
  const matchButton = button('匹配此目录的同名记录','button secondary',matchSameNames); matchButton.id='scanRelinkMatch';
  if(plan.truncated)matchButton.title='当前预览只显示部分记录，请分批处理后再使用同名匹配。';
  const resetButton = button('全部作为新 Bug','text-button',()=>{assignments.clear();refresh();announce.textContent='已取消全部旧记录关联。';});
  resetButton.id='scanRelinkReset';
  tools.append(batchLabel,matchButton,resetButton);
  const announce = node('p','scan-relink-announcement'); announce.id='scanRelinkAnnouncement'; announce.setAttribute('aria-live','polite');
  const list = node('div','scan-relink-rows'); list.setAttribute('aria-label','新旧文件夹关联');
  plan.targets.forEach((target,index)=>{
    const card=node('article','scan-relink-row');
    const targetInfo=node('div','scan-relink-target');
    targetInfo.append(node('span','scan-relink-caption','新文件夹 '+(index+1)),node('h3','',scanRelinkText(target.folder_name,'未命名文件夹')));
    if(target.folder)targetInfo.append(node('p','scan-relink-path',scanRelinkText(target.folder)));
    const selection=node('div','scan-relink-selection');
    const label=node('label','scan-relink-label');
    label.append(node('span','','沿用旧 Bug（可选）'));
    const select=node('select'); select.id='scanRelinkTarget-'+index;
    select.setAttribute('aria-label','为 '+scanRelinkText(target.folder_name)+' 选择旧 Bug');
    // Only the focused selector expands its candidates: 300 folders never create 90,000 options.
    select.addEventListener('focus',()=>{if(activeRow!==index){activeRow=index;refresh();}});
    label.append(select);
    const detail=node('div','scan-relink-detail'); detail.id='scanRelinkDetail-'+index;
    select.setAttribute('aria-describedby',detail.id);
    select.addEventListener('change',()=>{
      const next=select.value===''?null:Number(select.value);
      const currentBatch=selectedBatch(index);
      if(next!==null && (!Number.isInteger(next) || !sources[next] ||
        [...assignments].some(([targetIndex,sourceIndex])=>targetIndex!==index&&sourceIndex===next) ||
        (currentBatch && sources[next].source_batch_key!==currentBatch))) {
        announce.textContent='这条旧记录已被占用，或来自另一个旧目录。请先取消已有的关联。';
      } else {
        if(next===null)assignments.delete(index);else assignments.set(index,next);
        announce.textContent='';
      }
      refresh();
    });
    selection.append(label,detail); card.append(targetInfo,selection); list.append(card);
    rows.push({select,detail});
  });
  body.append(intro,root,policy,tools,announce,list);
  const footer=node('div','modal-footer scan-relink-footer');
  const hint=node('span','footer-hint'); hint.id='scanRelinkHint'; hint.setAttribute('aria-live','polite');
  const cancel=button('取消扫描','button secondary',()=>dialog.close()); cancel.id='scanRelinkCancel';
  let result=null;
  const confirm=button('继续扫描','button primary',()=>{
    const relinks=[...assignments].map(([index,sourceIndex])=>{
      const source=sources[sourceIndex];
      return {folder_name:plan.targets[index].folder_name,source_batch_key:source.source_batch_key,bug_id:source.bug_id,review_token:source.review_token};
    });
    result=relinks.length?{path,relink_plan_id:plan.plan_id,relinks}:{path};
    dialog.close();
  }); confirm.id='scanRelinkConfirm';
  footer.append(hint,cancel,confirm); dialog.append(header,body,footer);
  document.body.append(dialog);

  function selectedBatch(excludeIndex=-1) {
    for (const [index,sourceIndex] of assignments) if(index!==excludeIndex)return sources[sourceIndex].source_batch_key;
    return '';
  }

  function refresh() {
    const activeBatch=selectedBatch();
    const filterBatch=activeBatch||batchSelect.value;
    const owners=new Map([...assignments].map(([index,sourceIndex])=>[sourceIndex,index]));
    rows.forEach(({select,detail},index)=>{
      const chosen=assignments.get(index);
      const fresh=node('option','','作为新 Bug'); fresh.value='';
      select.replaceChildren(fresh);
      sources.forEach((source,sourceIndex)=>{
        if(sourceIndex!==chosen && (index!==activeRow || (filterBatch && source.source_batch_key!==filterBatch)))return;
        const description=scanRelinkStatus(source)+' · '+scanRelinkText(source.title,source.original_title)+' · '+scanRelinkText(source.old_folder);
        const option=node('option','',description);option.value=String(sourceIndex);option.title=description;
        option.disabled=owners.has(sourceIndex)&&owners.get(sourceIndex)!==index;
        select.append(option);
      });
      select.value=chosen===undefined?'':String(chosen);
      detail.replaceChildren();
      if(chosen===undefined) {
        detail.append(node('p','scan-relink-new','新建草稿，使用当前文件夹名作为初始标题。'));
      } else {
        const source=sources[chosen];
        detail.append(node('p','scan-relink-saved-title','保留标题：'+scanRelinkText(source.title,source.original_title)),
          node('p','scan-relink-path','旧文件夹名：'+scanRelinkText(source.original_title)),
          node('p','scan-relink-path','原路径：'+scanRelinkText(source.old_folder)),
          node('p','scan-relink-state',scanRelinkStatus(source)));
        if(source.settings_note)detail.append(node('p','scan-relink-settings',scanRelinkText(source.settings_note)));
      }
    });
    for(const option of batchSelect.children)option.disabled=!!(activeBatch && option.value && option.value!==activeBatch);
    matchButton.disabled=plan.truncated || !batchSelect.value || !!(activeBatch && batchSelect.value!==activeBatch);
    resetButton.disabled=!assignments.size;
    hint.textContent=assignments.size+' 条沿用旧记录 · '+(plan.target_count-assignments.size)+' 条作为新 Bug';
    confirm.textContent=assignments.size?'确认关联并扫描':'继续扫描（不沿用旧记录）';
  }

  function matchSameNames() {
    const key=batchSelect.value,activeBatch=selectedBatch();
    if(plan.truncated || !key || (activeBatch && key!==activeBatch))return;
    const names=new Map();
    sources.forEach((source,index)=>{
      if(source.source_batch_key!==key)return;
      const name=scanRelinkText(source.original_title);
      if(!names.has(name))names.set(name,[]);
      names.get(name).push(index);
    });
    const used=new Set(assignments.values());
    let matched=0;
    plan.targets.forEach((target,index)=>{
      if(assignments.has(index))return;
      const matches=names.get(scanRelinkText(target.folder_name));
      if(matches?.length===1 && !used.has(matches[0])) {
        assignments.set(index,matches[0]); used.add(matches[0]); ++matched;
      }
    });
    refresh();
    announce.textContent=matched?'已匹配 '+matched+' 条名称完全相同且唯一的旧记录，请核对下方关联后再扫描。':'没有找到可沿用的同名唯一记录，可在下方逐条选择。';
  }
  batchSelect.addEventListener('change',refresh);
  refresh();
  return new Promise((resolve,reject)=>{
    dialog.addEventListener('close',()=>{
      dialog.remove();
      previousFocus?.focus?.();
      resolve(result);
    },{once:true});
    try {dialog.showModal();cancel.focus();}
    catch(error){dialog.remove();reject(error);}
  });
}
