/* Screenshot guide is independent of the review view: opening it never rebuilds a Bug. */
"use strict";

(() => {
  const SVG_NS='http://www.w3.org/2000/svg';
  // Coordinates are percentages of each unmodified screenshot's natural size.
  const pages=[
  {
    "short": "扫描",
    "title": "先扫描当天的 Bug",
    "image": "/help/workbuddy-1-scan.jpg",
    "width": 1280,
    "height": 720,
    "alt": "合成示例工作台：顶部文件夹入口和 WorkBuddy 整理按钮。",
    "intro": "选择当天的总文件夹，扫描后打开 WorkBuddy 整理。",
    "steps": [
      "点击顶部文件夹入口，选择自己的 Bug 总文件夹。",
      "在文件夹弹层中点击「扫描 Bug」。",
      "打开右上角的「WorkBuddy 整理」。"
    ],
    "boxes": [
      {
        "n": 1,
        "x": 16.3,
        "y": 2,
        "w": 8.5,
        "h": 5.5
      },
      {
        "n": 3,
        "x": 63.2,
        "y": 2,
        "w": 12,
        "h": 5.5
      }
    ],
    "arrows": []
  },
  {
    "short": "复制",
    "title": "复制本次整理任务",
    "image": "/help/workbuddy-2-send.jpg",
    "width": 1280,
    "height": 720,
    "alt": "合成示例：本机连接已开启，右上角可以复制当次整理任务。",
    "intro": "开启本机连接，复制这一次的整理任务，下一步到 WorkBuddy 中发送。",
    "steps": [
      "开启本机连接，确认状态为「本机连接已开启」。",
      "点击「复制任务给 WorkBuddy」。"
    ],
    "boxes": [
      {
        "n": 1,
        "x": 2.5,
        "y": 11.5,
        "w": 14,
        "h": 3.5
      },
      {
        "n": 2,
        "x": 78.5,
        "y": 11,
        "w": 14,
        "h": 5
      }
    ],
    "arrows": []
  },
  {
    "short": "WorkBuddy",
    "title": "在 WorkBuddy 中发送任务",
    "taskExample": true,
    "intro": "使用当次复制的任务，附上允许发送的失败用例。",
    "steps": [
      "按客户端提供的流程安装并启用 bugdesk-workbuddy 技能。",
      "粘贴当次任务，并在末尾附上失败用例，保留表头和换行。",
      "选择客户端中可用、适合处理多行表格的模型，然后发送。",
      "确认技能已执行，回到 BugDesk 看到整理建议后再核对。"
    ],
    "boxes": [],
    "flow": true,
    "note": "示意内容不能直接建立连接，请使用当次复制的完整任务。",
    "recovery": "请按 bugdesk-workbuddy 技能执行，并把整理建议回传 BugDesk。"
  },
  {
    "short": "预览",
    "title": "悬停看内容，点击才选用",
    "image": "/help/workbuddy-3-preview.jpg",
    "width": 1280,
    "height": 720,
    "alt": "合成示例：Bug 清单、来源用例和四项测试事实并排显示。",
    "intro": "鼠标移到用例上即可预览。高亮对应正在查看的内容，圆点表示已选用。",
    "steps": [
      "在左侧查看需要整理的 Bug。",
      "看来源用例的前置条件、步骤、实际结果和预期结果。",
      "确认匹配后，点击用例或「选用此用例」。"
    ],
    "boxes": [],
    "arrows": [],
    "legend": true
  },
  {
    "short": "导入",
    "title": "核对后，把内容填入草稿",
    "image": "/help/workbuddy-4-import.jpg",
    "width": 1280,
    "height": 720,
    "alt": "合成示例：勾选本条已核对，再点击导入已核对 Bug。",
    "intro": "核对真实测试事实后勾选，再导入 Bug 草稿。",
    "steps": [
      "勾选「本条已核对」，继续核对其他 Bug。",
      "点击「导入已核对 Bug」，把内容填入草稿。"
    ],
    "boxes": [
      {
        "n": 1,
        "x": 29.7,
        "y": 84.2,
        "w": 13,
        "h": 4
      },
      {
        "n": 2,
        "x": 84.6,
        "y": 91.2,
        "w": 13,
        "h": 5
      }
    ],
    "arrows": [],
    "note": "默认只补空白。需要替换已有内容时，再勾选「覆盖已有内容」。"
  }
];

  let guide=null,pageIndex=0,returnFocus=null,taskSlot=null,stage=null,pageTitle=null,
    intro=null,exampleNote=null,stepList=null,extra=null,body=null,sidebar=null,pageButtons=[],previous=null,next=null,counter=null,zoom=null,zoomed=false;

  function el(tag,className,text){const item=document.createElement(tag);if(className)item.className=className;if(text!==undefined)item.textContent=text;return item;}
  function control(text,className,action){const item=el('button',className,text);item.type='button';item.addEventListener('click',action);return item;}
  function svgEl(tag,attrs){const item=document.createElementNS(SVG_NS,tag);Object.entries(attrs||{}).forEach(([key,value])=>item.setAttribute(key,String(value)));return item;}

  function closeGuide(){if(guide?.open)guide.close();}

  function annotationLayer(page){
    const overlay=el('div','workbuddy-guide-annotations');overlay.setAttribute('aria-hidden','true');
    const arrows=svgEl('svg',{viewBox:'0 0 '+page.width+' '+page.height,preserveAspectRatio:'none',class:'workbuddy-guide-arrows'});
    const defs=svgEl('defs'),marker=svgEl('marker',{id:'workBuddyGuideArrow',markerWidth:8,markerHeight:8,refX:6.5,refY:4,orient:'auto'});
    marker.append(svgEl('path',{d:'M 0 0 L 7 4 L 0 8',fill:'none',stroke:'currentColor','stroke-width':1.7,'stroke-linecap':'round','stroke-linejoin':'round'}));defs.append(marker);arrows.append(defs);
    (page.arrows||[]).forEach(([x1,y1,x2,y2])=>{
      arrows.append(svgEl('path',{d:'M '+(x1*page.width/100)+' '+(y1*page.height/100)+' L '+(x2*page.width/100)+' '+(y2*page.height/100),fill:'none','marker-end':'url(#workBuddyGuideArrow)','vector-effect':'non-scaling-stroke'}));
    });
    overlay.append(arrows);
    page.boxes.forEach(box=>{
      const rectangle=el('span','workbuddy-guide-box'+(box.pin==='below'?' pin-below':'')+(box.outline===false?' pin-only':''));rectangle.style.left=box.x+'%';rectangle.style.top=box.y+'%';rectangle.style.width=box.w+'%';rectangle.style.height=box.h+'%';
      const pin=el('span','workbuddy-guide-pin',String(box.n));if(box.pinPoint){pin.classList.add('custom-position');pin.style.left=((box.pinPoint[0]-box.x)/box.w*100)+'%';pin.style.top=((box.pinPoint[1]-box.y)/box.h*100)+'%';}rectangle.append(pin);overlay.append(rectangle);
    });
    return overlay;
  }

  function renderPage(index){
    pageIndex=Math.max(0,Math.min(pages.length-1,index));const page=pages[pageIndex];zoomed=false;if(body)body.scrollTop=0;if(sidebar)sidebar.scrollTop=0;
    pageTitle.textContent=page.title;intro.textContent=page.intro;exampleNote.textContent=page.exampleNote||'';exampleNote.hidden=!page.exampleNote;stepList.replaceChildren();
    page.steps.forEach((text,index)=>{const item=el('li');item.append(el('span','workbuddy-guide-step-number',String(index+1)),el('span','',text));stepList.append(item);});
    extra.replaceChildren();
    if(page.flow){const flow=el('div','workbuddy-guide-flow');flow.append(el('span','','复制的任务'),el('b','','＋'),el('span','','失败用例'),el('b','','→'),el('strong','','一起发给 WorkBuddy'));extra.append(flow);}
    if(page.legend){
      const legend=el('div','workbuddy-guide-legend');
      const chosen=el('span'),displayed=el('span');chosen.append(el('i','workbuddy-guide-radio'),document.createTextNode('圆点：已选用'));displayed.append(el('i','workbuddy-guide-highlight'),document.createTextNode('高亮：正在查看'));
      legend.append(chosen,displayed);extra.append(legend);
    }
    if(page.note)extra.append(el('p','workbuddy-guide-note',page.note));
    if(page.advice&&!page.sources)extra.append(el('p','workbuddy-guide-model-advice',page.advice));
    if(page.recovery){const recovery=el('details','workbuddy-guide-recovery');recovery.append(el('summary','','如果只回复文字，没有收到整理建议'),el('p','','可以补发这一句：'),el('blockquote','',page.recovery));extra.append(recovery);}
    if(page.sources){
      const sources=el('details','workbuddy-guide-sources');sources.append(el('summary','','模型设置与官方资料'));
      if(page.advice)sources.append(el('p','workbuddy-guide-model-advice',page.advice));
      const explanation=el('p','','WorkBuddy 已接入该模型。截图未展开思考设置，具体菜单以客户端为准。');
      const links=el('div','workbuddy-guide-source-links');page.sources.forEach(source=>{const link=el('a','',source.title);link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';links.append(link);});sources.append(explanation,links);extra.append(sources);
    }
    stage.classList.remove('is-zoomed');stage.scrollLeft=0;stage.scrollTop=0;zoom.hidden=!!page.taskExample;zoom.textContent='放大截图';zoom.setAttribute('aria-pressed','false');
    stage.setAttribute('aria-label',page.taskExample?'发送任务操作示意':'步骤截图，可放大并滚动查看');
    if(page.taskExample){
      const example=el('section','workbuddy-guide-task-example');
      example.append(el('span','workbuddy-guide-task-badge','操作示意 · 使用当次复制的任务'),el('h3','','发送任务与失败用例'));
      const task=el('pre','','使用 bugdesk-workbuddy 技能。\n\n[粘贴 BugDesk 当次复制的完整任务]\n\n下面是失败用例：\n[粘贴允许发送的表格内容，保留表头与换行]');
      example.append(task,el('p','','确认已识别技能 → 发送 → 等待执行完成 → 回到 BugDesk 核对建议'));stage.replaceChildren(example);
    }else{
    const figure=el('figure','workbuddy-guide-figure'),image=el('img','workbuddy-guide-image');figure.style.aspectRatio=page.width+' / '+page.height;figure.style.setProperty('--workbuddy-guide-ratio',String(page.width/page.height));figure.style.setProperty('--workbuddy-guide-natural-width',page.width+'px');image.id='workBuddyGuideImage';image.alt=page.alt;image.width=page.width;image.height=page.height;image.draggable=false;image.decoding='async';
    const missing=el('p','workbuddy-guide-image-error','截图暂未载入，可以按下方步骤操作。');missing.hidden=true;
    image.addEventListener('error',()=>{missing.hidden=false;figure.classList.add('image-missing');});
    image.src=page.image;figure.append(image,annotationLayer(page),missing);stage.replaceChildren(figure);
    }
    pageButtons.forEach((item,index)=>{item.classList.toggle('active',index===pageIndex);if(index===pageIndex)item.setAttribute('aria-current','step');else item.removeAttribute('aria-current');});
    previous.disabled=pageIndex===0;next.textContent=pageIndex===pages.length-1?'返回核对':'下一步';counter.textContent=(pageIndex+1)+' / '+pages.length;
  }

  function toggleZoom(){
    zoomed=!zoomed;stage.classList.toggle('is-zoomed',zoomed);zoom.textContent=zoomed?'适应窗口':'放大截图';zoom.setAttribute('aria-pressed',String(zoomed));stage.scrollLeft=0;stage.scrollTop=0;
  }

  function installWorkBuddyGuide(taskNode){
    if(guide){if(taskNode&&taskNode.parentElement!==taskSlot){taskNode.hidden=true;taskSlot.replaceChildren(taskNode);}return guide;}
    guide=el('dialog','workbuddy-guide-modal');guide.id='workBuddyGuideDialog';guide.setAttribute('aria-labelledby','workBuddyGuideTitle');
    const header=el('header','workbuddy-guide-header'),titleGroup=el('div');
    titleGroup.append(el('span','workbuddy-guide-eyebrow','WORKBUDDY · '+pages.length+' 步图解'));
    const title=el('h2','','照着做，整理当天的 Bug');title.id='workBuddyGuideTitle';titleGroup.append(title);
    const close=control('','workbuddy-guide-close',closeGuide);close.id='workBuddyGuideClose';close.setAttribute('aria-label','关闭使用图解');close.autofocus=true;
    const closeIcon=svgEl('svg',{viewBox:'0 0 24 24','aria-hidden':'true'});closeIcon.append(svgEl('path',{d:'M 6 6 L 18 18 M 18 6 L 6 18'}));close.append(closeIcon);header.append(titleGroup,close);
    taskSlot=el('div','workbuddy-guide-task-slot');taskSlot.id='workBuddyGuideTaskSlot';if(taskNode){taskNode.hidden=true;taskSlot.append(taskNode);}
    const nav=el('nav','workbuddy-guide-pages');nav.id='workBuddyGuidePages';nav.setAttribute('aria-label','使用图解步骤');
    pageButtons=pages.map((page,index)=>{const item=control('','workbuddy-guide-page',()=>renderPage(index));item.setAttribute('aria-label','第 '+(index+1)+' 步：'+page.title);item.append(el('span','workbuddy-guide-page-number',String(index+1)),el('span','',page.short));nav.append(item);return item;});
    body=el('div','workbuddy-guide-body');const pageHeader=el('div','workbuddy-guide-page-header'),description=el('div');
    pageTitle=el('h3');pageTitle.id='workBuddyGuidePageTitle';intro=el('p');description.append(pageTitle,intro);zoom=control('放大截图','workbuddy-guide-zoom',toggleZoom);zoom.id='workBuddyGuideZoom';zoom.setAttribute('aria-pressed','false');pageHeader.append(description,zoom);
    const workspace=el('div','workbuddy-guide-workspace');sidebar=el('aside','workbuddy-guide-sidebar');sidebar.setAttribute('aria-label','当前步骤说明');
    exampleNote=el('p','workbuddy-guide-example-note');exampleNote.hidden=true;
    stage=el('div','workbuddy-guide-image-viewport');stage.id='workBuddyGuideStage';stage.tabIndex=0;stage.setAttribute('aria-label','步骤截图，可放大并滚动查看');
    stepList=el('ol','workbuddy-guide-steps');extra=el('div','workbuddy-guide-extra');sidebar.append(exampleNote,stepList,extra);workspace.append(stage,sidebar);body.append(pageHeader,workspace);
    const footer=el('footer','workbuddy-guide-footer');previous=control('上一步','workbuddy-guide-nav-button',()=>renderPage(pageIndex-1));previous.id='workBuddyGuidePrevious';counter=el('span','workbuddy-guide-counter');counter.id='workBuddyGuideCounter';counter.setAttribute('aria-live','polite');counter.setAttribute('aria-atomic','true');next=control('下一步','workbuddy-guide-nav-button primary',()=>{if(pageIndex===pages.length-1)closeGuide();else renderPage(pageIndex+1);});next.id='workBuddyGuideNext';footer.append(previous,counter,next);
    guide.append(header,taskSlot,nav,body,footer);document.body.append(guide);renderPage(0);
    guide.addEventListener('cancel',event=>{event.preventDefault();event.stopPropagation();closeGuide();});
    guide.addEventListener('keydown',event=>{
      event.stopPropagation();
      if(event.key==='Escape'){event.preventDefault();closeGuide();return;}
      if(event.ctrlKey||event.metaKey||event.altKey||event.target.closest('input,textarea,select,[contenteditable="true"]')||(zoomed&&stage.contains(event.target)))return;
      if(event.key==='ArrowLeft'){event.preventDefault();if(pageIndex>0)renderPage(pageIndex-1);}
      else if(event.key==='ArrowRight'){event.preventDefault();if(pageIndex<pages.length-1)renderPage(pageIndex+1);}
    });
    let backdropStart=false;
    const outside=event=>{const box=guide.getBoundingClientRect();return event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom;};
    guide.addEventListener('pointerdown',event=>{backdropStart=event.target===guide&&outside(event);});
    guide.addEventListener('pointercancel',()=>{backdropStart=false;});
    guide.addEventListener('click',event=>{if(event.target===guide&&backdropStart&&outside(event))closeGuide();backdropStart=false;event.stopPropagation();});
    guide.addEventListener('submit',event=>{event.preventDefault();event.stopPropagation();});
    guide.addEventListener('close',()=>{const target=returnFocus;returnFocus=null;const owner=target?.closest?.('dialog');if(target?.isConnected&&(!owner||owner.open))target.focus({preventScroll:true});});
    return guide;
  }

  function openWorkBuddyGuide(){
    if(!guide)installWorkBuddyGuide();if(guide.open)return;
    returnFocus=document.activeElement;renderPage(0);guide.showModal();
  }

  globalThis.installWorkBuddyGuide=installWorkBuddyGuide;
  globalThis.openWorkBuddyGuide=openWorkBuddyGuide;
})();
