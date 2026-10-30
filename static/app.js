/* WinLine app.js — все скрипты фронта в одном файле (порядок как был в index.html) */

/* ===== telegram-gifts.js ===== */
(()=>{
'use strict';
const records=new Map(),dataCache=new Map();let runtime=null,frame=0;
function slugFor(image){
 if(image.closest('#prizeGrid,#stakingPositions,#stakingEligible'))return null;
 const value=image.dataset.nftSlug||image.getAttribute('src')||'';
 const match=value.match(/(?:nft-img\/|t\.me\/nft\/|^)([a-z][a-z0-9]{1,63}-[1-9][0-9]{0,10})(?:\.png|$)/i);return match?match[1].toLowerCase():null;
}
function loadRuntime(){
 if(window.lottie)return Promise.resolve(window.lottie);
 if(!runtime)runtime=new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/static/vendor/lottie_light.min.js?v=5.13.0';script.onload=()=>window.lottie?resolve(window.lottie):reject(new Error('lottie'));script.onerror=()=>{runtime=null;script.remove();reject(new Error('lottie'))};document.head.append(script)});
 return runtime;
}
function loadData(slug){
 if(!dataCache.has(slug)){
  const promise=fetch('/nft-animation/'+slug+'.json').then(response=>{if(!response.ok)throw new Error('animation');return response.json()});
  dataCache.set(slug,promise);if(dataCache.size>48)dataCache.delete(dataCache.keys().next().value);
 }
 return dataCache.get(slug);
}
function position(record){
 const image=record.image,layer=record.layer;if(!layer)return;
 const style=getComputedStyle(image);Object.assign(layer.style,{left:image.offsetLeft+'px',top:image.offsetTop+'px',width:image.offsetWidth+'px',height:image.offsetHeight+'px',borderRadius:style.borderRadius,transform:style.transform,transformOrigin:style.transformOrigin});
}
function destroy(record){record.animation?.destroy();record.layer?.remove();record.image.classList.remove('telegram-gift-playing');resize.unobserve(record.image);intersection.unobserve(record.image);records.delete(record.image)}
function schedule(){if(!frame)frame=requestAnimationFrame(()=>{frame=0;synchronize()})}
async function start(record){
 record.loading=true;
 try{
  const [lottie,data]=await Promise.all([loadRuntime(),loadData(record.slug)]);
  if(!record.image.isConnected||records.get(record.image)!==record)return;
  const parent=record.image.parentElement;if(getComputedStyle(parent).position==='static')parent.style.position='relative';
  const layer=document.createElement('span');layer.className='telegram-gift-animation';layer.setAttribute('aria-hidden','true');parent.append(layer);record.layer=layer;position(record);
  const animation=lottie.loadAnimation({container:layer,renderer:'svg',loop:true,autoplay:false,animationData:structuredClone(data),rendererSettings:{preserveAspectRatio:'xMidYMid meet',progressiveLoad:true}});record.animation=animation;
  animation.addEventListener('DOMLoaded',()=>{if(record.image.isConnected){record.ready=true;record.image.classList.add('telegram-gift-playing');schedule()}});
  animation.addEventListener('data_failed',()=>{record.failed=true;destroy(record)});
 }catch(_){record.failed=true;record.layer?.remove();record.layer=null}
 finally{record.loading=false;schedule()}
}
function synchronize(){
 let playing=0,loading=[...records.values()].filter(record=>record.loading).length;
 for(const record of [...records.values()]){
  if(!record.image.isConnected||slugFor(record.image)!==record.slug){destroy(record);continue}
  const visible=record.visible&&!document.hidden&&record.image.getClientRects().length>0;
  if(visible&&playing<6){playing++;if(!record.animation&&!record.loading&&!record.failed&&loading<2){loading++;start(record)}if(record.ready)record.animation.play()}
  else record.animation?.pause();
 }
}
const resize=new ResizeObserver(entries=>{for(const entry of entries){const record=records.get(entry.target);if(record)position(record)}});
const intersection=new IntersectionObserver(entries=>{for(const entry of entries){const record=records.get(entry.target);if(record)record.visible=entry.isIntersecting}schedule()},{rootMargin:'40px'});
function scan(root){
 const images=[...(root.matches?.('img')?[root]:[]),...root.querySelectorAll?.('img')||[]];
 for(const image of images){const slug=slugFor(image),old=records.get(image);if(old&&old.slug===slug)continue;if(old)destroy(old);if(!slug)continue;
  const record={image,slug,visible:false,loading:false,ready:false,failed:false};records.set(image,record);intersection.observe(image);resize.observe(image);image.addEventListener('load',()=>position(record),{once:true});
 }
 schedule();
}
function boot(){scan(document.body);new MutationObserver(changes=>{for(const change of changes){if(change.type==='attributes'&&change.target.tagName==='IMG')scan(change.target);for(const node of change.addedNodes)if(node.nodeType===1&&!node.closest?.('.telegram-gift-animation'))scan(node)}schedule()}).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['src','data-nft-slug']});document.addEventListener('visibilitychange',schedule)}
window.TelegramGiftMedia={scan};if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
;

/* ===== scene-details.js ===== */
try{
(() => {
 'use strict';
 const world=document.getElementById('meadowWorld'),root=document.documentElement;
 if(!world)return;
 const NS='http://www.w3.org/2000/svg';
 const wheel=document.querySelector('.wheel-wrap');
 let anchorX=.5,anchor=.4,frame=0,lastWheelSize=Math.min(innerWidth*.88,innerHeight*.4,350);

 const landmarks={meadow:{x:.5,y:.531,width:.109},halloween:{x:.5,y:.568,width:.12},basement:{x:.5,y:.501,width:.115}};
 function fit(){
  frame=0;
  const w=innerWidth,h=innerHeight,dpr=devicePixelRatio||1,box=wheel?.getBoundingClientRect();
  if(box?.width&&box.height){let centre=wheel.offsetWidth*.5;for(let node=wheel;node;node=node.offsetParent)centre+=node.offsetLeft;anchorX=centre/w;anchor=(box.top+box.height*.67)/h;lastWheelSize=box.width;}
  const target=Math.max(0,Math.min(h,h*anchor)),wheelSize=lastWheelSize;
  for(const kind of ['meadow','halloween','basement']){
   const img=kind==='meadow'?world.querySelector('.day'):kind==='basement'?document.querySelector('#basementWorld .basement-lit'):document.getElementById('halloweenNightPng');
   const ratio=kind==='halloween'&&root.dataset.scenePortrait==='on'?941/1672:1672/941;
   const l=landmarks[kind];
   // halloween: plain cover, centred, pinned to the bottom (the grave sits behind the buttons)
   const cover=kind==='halloween';
   const height=Math.ceil((cover?Math.max(h,w/ratio):Math.max(h,w/ratio,target/l.y,(h-target)/(1-l.y),wheelSize*(kind==='basement'?.48:.65)/(l.width*ratio)))*dpr)/dpr;
   const width=Math.ceil(height*ratio*dpr)/dpr;
   const x=cover?Math.round((w-width)/2*dpr)/dpr:Math.max(w-width,Math.min(0,Math.round((w*anchorX-width*l.x)*dpr)/dpr));
   const y=cover?h-height:Math.max(h-height,Math.min(0,Math.round((target-height*l.y)*dpr)/dpr));
   const targetNode=root;
   const vars=kind==='basement'?{'--bs-scene-w':width,'--bs-scene-h':height,'--bs-scene-x':x,'--bs-scene-y':y}:kind==='meadow'?{'--ms-w':width,'--ms-h':height,'--ms-rest-x':x,'--ms-top':y}:{'--hw-scene-w':width,'--hw-scene-h':height,'--hw-scene-x':x,'--hw-scene-y':y};
   for(const [k,v]of Object.entries(vars))targetNode.style.setProperty(k,v+'px');
  }
 }
 const schedule=()=>{if(!frame)frame=requestAnimationFrame(fit)};
 fit();new ResizeObserver(schedule).observe(wheel);
 addEventListener('resize',schedule,{passive:true});window.window.visualViewport?.addEventListener('resize',schedule);
 for(const img of [...world.querySelectorAll('.ms-img'),document.getElementById('halloweenNightPng')])img?.addEventListener('load',schedule);
 new MutationObserver(schedule).observe(root,{attributes:true,attributeFilter:['data-theme','data-halloween','data-basement','data-scene-portrait']});
 new ResizeObserver(schedule).observe(document.getElementById('view-upgrade'));
 new MutationObserver(schedule).observe(document.getElementById('view-upgrade'),{attributes:true,attributeFilter:['hidden','style','class']});
 document.fonts?.ready.then(schedule);
 if(window.PerformanceObserver){try{new PerformanceObserver(schedule).observe({type:'layout-shift',buffered:true})}catch(_){}}
})();
}catch(e){console.error("[app.js] scene-details.js",e)}
;

/* ===== optimization.js ===== */
try{
(() => {
 'use strict';
 const root=document.documentElement,key='hatdrop.performance.v1';
 let enabled=false,decided=false,previousFocus=null;
 try{const p=JSON.parse(localStorage.getItem(key)||'{}');enabled=p.enabled===true;decided=p.decided===true}catch(_){}
 const copy={
  ru:{title:'Режим оптимизации',intro:'Настройте плавность игры',recommend:'На этом устройстве рекомендуем включить оптимизацию для более плавной игры.',normal:'Выберите, сколько анимаций оставить. Этот режим можно изменить в настройках профиля.',note:'Упрощает фоновые эффекты и декоративные анимации.',apply:'Применить'},
  en:{title:'Optimization mode',intro:'Choose your animation settings',recommend:'We recommend optimization on this device for smoother play.',normal:'Choose how many animations to keep. You can change this in profile settings.',note:'Simplifies background effects and decorative animations.',apply:'Apply'},
  zh:{title:'优化模式',intro:'设置游戏流畅度',recommend:'建议在此设备上启用优化，让游戏更流畅。',normal:'选择保留多少动画。您可以在个人设置中更改。',note:'简化背景效果和装饰动画。',apply:'应用'}
 };
 const words=()=>copy[root.dataset.lang]||copy.ru;
 const dialog=document.getElementById('optimizationModal'),intro=document.getElementById('optimizationIntroToggle'),setting=document.getElementById('optimizationSetting');
 if(!dialog||!intro||!setting)return;
 function render(){
  const t=words();
  document.querySelectorAll('[data-optimization-text]').forEach(e=>{e.textContent=t[e.dataset.optimizationText]||''});
  for(const input of [intro,setting])input.setAttribute('aria-label',t.title);
  setting.checked=enabled;
 }
 function apply(value,persist=true){
  enabled=value===true;
  root.dataset.optimized=enabled?'on':'off';
  if(persist){decided=true;try{localStorage.setItem(key,JSON.stringify({enabled,decided:true}))}catch(_){}}
  render();
  window.dispatchEvent(new CustomEvent('hatdrop:performancechange',{detail:{enabled}}));
 }
 function close(){
  dialog.hidden=true;
  const tour=document.getElementById('tourLayer');if(tour)tour.inert=false;
  if(previousFocus?.isConnected)previousFocus.focus({preventScroll:true});
 }
 document.getElementById('optimizationApply').addEventListener('click',()=>{apply(intro.checked);close()});
 setting.addEventListener('change',()=>apply(setting.checked));
 dialog.addEventListener('keydown',e=>{
  if(e.key==='Escape'){e.preventDefault();apply(enabled);close()}
  if(e.key==='Tab'){
   const controls=[intro,document.getElementById('optimizationApply')];
   if(e.shiftKey&&document.activeElement===controls[0]){e.preventDefault();controls[1].focus()}
   else if(!e.shiftKey&&document.activeElement===controls[1]){e.preventDefault();controls[0].focus()}
  }
 });
 new MutationObserver(render).observe(root,{attributes:true,attributeFilter:['data-lang']});
 apply(enabled,false);


 function sampleFrames(){
  return new Promise(resolve=>{
   let raf=0,last=0,done=false;const deltas=[];
   const finish=()=>{if(done)return;done=true;cancelAnimationFrame(raf);clearTimeout(timeout);resolve(deltas.length>=18?deltas.sort((a,b)=>a-b)[Math.floor(deltas.length*.75)]:null)};
   const tick=t=>{
    if(document.hidden){finish();return}
    if(last&&t-last<180)deltas.push(t-last);last=t;
    if(deltas.length>=36)finish();else raf=requestAnimationFrame(tick);
   };
   const timeout=setTimeout(finish,1800);raf=requestAnimationFrame(tick);
  });
 }
 async function firstVisit(){
  if(decided)return;
  await new Promise(resolve=>setTimeout(resolve,550));
  const frameTime=await sampleFrames();
  if(decided)return;
  if(document.hidden){document.addEventListener('visibilitychange',()=>{if(!document.hidden)firstVisit()},{once:true});return}
  const cores=Number(navigator.hardwareConcurrency)||0,memory=Number(navigator.deviceMemory)||0;
  const recommended=(cores>0&&cores<=4)||(memory>0&&memory<=2)||navigator.connection?.saveData===true||matchMedia('(prefers-reduced-motion: reduce)').matches||(frameTime!==null&&frameTime>32);
  const t=words();document.getElementById('optimizationRecommendation').textContent=recommended?t.recommend:t.normal;
  intro.checked=recommended;
  previousFocus=document.activeElement;
  const tour=document.getElementById('tourLayer');if(tour)tour.inert=true;
  dialog.hidden=false;intro.focus({preventScroll:true});
 }

 window.HatDropPerformance={setEnabled:apply,get enabled(){return enabled}};
 firstVisit();
})();
}catch(e){console.error("[app.js] optimization.js",e)}
;

/* ===== game-audio.js ===== */
try{
(() => {
  'use strict';
  const manifest = {"meadow": {"day": {"music": ["/static/audio/meadow-day-music.ogg?v=1", "/static/audio/meadow-day-music.mp3?v=1"], "ambience": ["/static/audio/meadow-day-ambience.ogg?v=1", "/static/audio/meadow-day-ambience.mp3?v=1"], "effects": {"navigation": "/static/audio/navigation.mp3?v=1", "spin": "/static/audio/upgrade-spin.mp3?v=1", "success": "/static/audio/upgrade-success.mp3?v=1", "miss": "/static/audio/upgrade-miss.mp3?v=1", "open": "/static/audio/meadow-chest-open.mp3?v=1", "reveal": "/static/audio/meadow-gold-reveal.mp3?v=1"}}, "night": {"music": ["/static/audio/meadow-night-music.ogg?v=1", "/static/audio/meadow-night-music.mp3?v=1"], "ambience": ["/static/audio/meadow-night-ambience.ogg?v=1", "/static/audio/meadow-night-ambience.mp3?v=1"], "effects": {"navigation": "/static/audio/navigation.mp3?v=1", "spin": "/static/audio/upgrade-spin.mp3?v=1", "success": "/static/audio/upgrade-success.mp3?v=1", "miss": "/static/audio/upgrade-miss.mp3?v=1", "open": "/static/audio/meadow-chest-open.mp3?v=1", "reveal": "/static/audio/meadow-gold-reveal.mp3?v=1"}}}, "halloween": {"day": {"effects": {"navigation": "/static/audio/halloween-navigation.mp3?v=1", "spin": "/static/audio/halloween-upgrade-spin.mp3?v=1", "success": "/static/audio/halloween-upgrade-success.mp3?v=1", "miss": "/static/audio/halloween-upgrade-miss.mp3?v=1", "open": "/static/audio/halloween-coffin-open.mp3?v=3", "reveal": "/static/audio/halloween-candy-reveal.mp3?v=1"}, "music": ["/static/audio/halloween-day-music.ogg?v=1", "/static/audio/halloween-day-music.mp3?v=1"], "ambience": ["/static/audio/halloween-day-ambience.ogg?v=3", "/static/audio/halloween-day-ambience.mp3?v=3"]}, "night": {"effects": {"navigation": "/static/audio/halloween-navigation.mp3?v=1", "spin": "/static/audio/halloween-upgrade-spin.mp3?v=1", "success": "/static/audio/halloween-upgrade-success.mp3?v=1", "miss": "/static/audio/halloween-upgrade-miss.mp3?v=1", "open": "/static/audio/halloween-coffin-open.mp3?v=2", "reveal": "/static/audio/halloween-candy-reveal.mp3?v=1"}, "music": ["/static/audio/halloween-night-music.ogg?v=1", "/static/audio/halloween-night-music.mp3?v=1"], "ambience": ["/static/audio/halloween-night-ambience.ogg?v=3", "/static/audio/halloween-night-ambience.mp3?v=3"]}}, "basement": {"day": {"music": ["/static/audio/basement-day-music.ogg?v=1", "/static/audio/basement-day-music.mp3?v=1"], "ambience": ["/static/audio/basement-day-ambience.ogg?v=4", "/static/audio/basement-day-ambience.mp3?v=4"], "effects": {"navigation": "/static/audio/basement-navigation.mp3?v=1", "success": "/static/audio/basement-success.mp3?v=1", "miss": "/static/audio/basement-miss.mp3?v=1", "spin": "/static/audio/basement-spin.mp3?v=1", "open": "/static/audio/basement-open.mp3?v=1", "reveal": "/static/audio/basement-reveal.mp3?v=1", "light": "/static/audio/basement-light.mp3?v=1", "shop-open": "/static/audio/basement-shop-open.mp3?v=1", "shop-tab": "/static/audio/basement-shop-tab.mp3?v=1", "purchase": "/static/audio/basement-purchase.mp3?v=1", "equip": "/static/audio/basement-equip.mp3?v=1", "gear-preview": "/static/audio/basement-gear-preview.mp3?v=1", "settings-open": "/static/audio/basement-settings-open.mp3?v=1", "reward": "/static/audio/basement-reward.mp3?v=1", "switch": "/static/audio/basement-switch.mp3?v=1", "light-on": "/static/audio/basement-light-on.mp3?v=1", "lamp-flicker": "/static/audio/basement-lamp-flicker.mp3?v=1"}}, "night": {"music": ["/static/audio/basement-night-music.ogg?v=1", "/static/audio/basement-night-music.mp3?v=1"], "ambience": ["/static/audio/basement-night-ambience.ogg?v=4", "/static/audio/basement-night-ambience.mp3?v=4"], "effects": {"navigation": "/static/audio/basement-navigation.mp3?v=1", "success": "/static/audio/basement-success.mp3?v=1", "miss": "/static/audio/basement-miss.mp3?v=1", "spin": "/static/audio/basement-spin.mp3?v=1", "open": "/static/audio/basement-open.mp3?v=1", "reveal": "/static/audio/basement-reveal.mp3?v=1", "light": "/static/audio/basement-light.mp3?v=1", "shop-open": "/static/audio/basement-shop-open.mp3?v=1", "shop-tab": "/static/audio/basement-shop-tab.mp3?v=1", "purchase": "/static/audio/basement-purchase.mp3?v=1", "equip": "/static/audio/basement-equip.mp3?v=1", "gear-preview": "/static/audio/basement-gear-preview.mp3?v=1", "settings-open": "/static/audio/basement-settings-open.mp3?v=1", "reward": "/static/audio/basement-reward.mp3?v=1", "switch": "/static/audio/basement-switch.mp3?v=1", "light-on": "/static/audio/basement-light-on.mp3?v=1", "lamp-flicker": "/static/audio/basement-lamp-flicker.mp3?v=1"}}}};
  const channels = ['music','ambience','effects'];
  const key = 'hatdrop.audio.v1';
  let prefs = {music:true, ambience:true, effects:true};
  try {
    const saved = JSON.parse(localStorage.getItem(key) || '{}');
    channels.forEach(channel => {if (typeof saved[channel] === 'boolean') prefs[channel] = saved[channel];});
  } catch (_) {}
  let context, master, unlocked = false, generation = 0, lastKey = '';
  const decodedSizes=new Map();const MAX_AUDIO_BYTES=64*1024*1024;
  const buffers = new Map(), loops = new Map(), effects = new Set();
  const root = document.documentElement;
  const hallDays=['sunday','monday','tuesday','wednesday','thursday','friday','saturday'];
  const scene=()=>({theme:root.dataset.hall==='on'?'hall':root.dataset.basement==='on'?'basement':root.dataset.halloween==='on'?'halloween':'meadow',sky:root.dataset.sky==='night'?'night':'day',curtains:root.dataset.hallCurtains==='closed'?'closed':'open',weekday:hallDays[new Date().getDay()]});
  const hallTracksCache=new Map();
  function tracksFor(c){if(c.theme!=='hall')return manifest[c.theme]?.[c.sky]||{};const key=c.weekday+'-'+c.sky+'-'+c.curtains;if(!hallTracksCache.has(key)){const state=c.sky+'-'+c.curtains,base='/static/hall/audio/';const effectNames={navigation:'navigation',spin:'spin-loop',success:'success',miss:'miss',open:'menu-open',reveal:'gift-reveal','shop-open':'shop-open','shop-tab':'navigation',purchase:'purchase',equip:'equip','gear-preview':'emerald-shimmer','settings-open':'menu-open',reward:'gift-reveal',switch:'navigation',light:'day-to-night','light-on':'night-to-day','lamp-flicker':'lamp-flicker','curtains-open':'curtains-open','curtains-close':'curtains-close','spin-start':'spin-start','spin-stop':'spin-stop'};hallTracksCache.set(key,{music:['ogg','mp3'].map(x=>base+'music/hall-'+c.weekday+'-'+state+'.'+x),ambience:['ogg','mp3'].map(x=>base+'ambience/hall-ambience-'+state+'.'+x+'?v=calm2'),effects:Object.fromEntries(Object.entries(effectNames).map(([k,v])=>[k,base+'effects/hall-'+v+'.mp3?v=calm2']))})}return hallTracksCache.get(key)}
  const active = () => !document.hidden && window.Telegram?.WebApp?.isActive !== false;
  const available = channel => Object.values(manifest).some(theme => Object.values(theme).some(sky => !!sky[channel]));
  function stopLoop(channel, seconds = .6) {
    const playing = loops.get(channel);
    if (!playing || !context) return;
    loops.delete(channel);
    const now=context.currentTime;
    playing.gain.gain.cancelScheduledValues(now);
    playing.gain.gain.setValueAtTime(playing.gain.gain.value,now);
    playing.gain.gain.linearRampToValueAtTime(0,now+seconds);
    try {playing.source.stop(now+seconds+.02);} catch (_) {}
  }
  function stopEffects() {
    for (const source of effects) {try {source.stop();} catch (_) {}}
    effects.clear();
  }
  function trimBuffers(){
    let total=[...decodedSizes.values()].reduce((a,b)=>a+b,0);
    for(const [url,size] of decodedSizes){
      if(total<=MAX_AUDIO_BYTES)break;
      if([...loops.values()].some(loop=>Array.isArray(loop.url)?loop.url.includes(url):loop.url===url))continue;
      buffers.delete(url);decodedSizes.delete(url);total-=size;
    }
  }
  async function buffer(url) {
    if (Array.isArray(url)) {
      for (const candidate of url) {
        try {return await buffer(candidate);} catch (_) {}
      }
      throw new Error('Audio unavailable');
    }
    if (!buffers.has(url)) buffers.set(url, fetch(url).then(response => {
      if (!response.ok) throw new Error('Audio unavailable');
      return response.arrayBuffer();
    }).then(bytes => context.decodeAudioData(bytes)).then(data=>{decodedSizes.set(url,data.length*data.numberOfChannels*4);trimBuffers();return data}).catch(error => {buffers.delete(url);decodedSizes.delete(url);throw error;}));
    const pending=buffers.get(url);if(pending){buffers.delete(url);buffers.set(url,pending);if(decodedSizes.has(url)){const size=decodedSizes.get(url);decodedSizes.delete(url);decodedSizes.set(url,size)}}return pending;
  }
  function renderControls() {
    document.querySelectorAll('[data-audio-channel]').forEach(input => {
      const channel=input.dataset.audioChannel;
      input.checked=prefs[channel] === true;
      input.closest('[data-audio-row]').hidden=!available(channel);
    });
    const note=document.getElementById('audioSceneNote');
    if (note) note.textContent='Музыка и окружение включаются независимо.';
    const off=document.getElementById('audioAllOff');
    if (off) off.disabled=!channels.some(channel => prefs[channel]);
  }
  async function reconcile(force = false) {
    const current=scene(), enabled=active();
    const signature=JSON.stringify([current,prefs,enabled,unlocked]);
    if (!force && signature===lastKey) return;
    lastKey=signature;
    const run=++generation;
    renderControls();
    const tracks=tracksFor(current);
    await Promise.all(['music','ambience'].map(async channel => {
      const url=tracks[channel];
      if (!enabled || !unlocked || !prefs[channel] || !url) {stopLoop(channel,enabled ? .08 : .02);return;}
      if (loops.get(channel)?.url===url) return;
      stopLoop(channel);
      try {
        const data=await buffer(url);
        if (generation!==run || !active() || !prefs[channel] || context.state!=='running') return;
        const source=context.createBufferSource(), gain=context.createGain();
        source.buffer=data;source.loop=true;source.connect(gain);gain.connect(master);
        gain.gain.setValueAtTime(0,context.currentTime);
        gain.gain.linearRampToValueAtTime(channel==='music' ? .85 : .7,context.currentTime+(current.theme==='hall'?1.6:.65));
        loops.set(channel,{source,gain,url});
        source.onended=()=>{source.disconnect();gain.disconnect();};
        source.start();
      } catch (_) {                                                      }
    }));
    trimBuffers();
    if (!enabled || !prefs.effects) stopEffects();
  }
  async function unlock() {
    if (!channels.some(channel => prefs[channel]) || !active()) return;
    try {
      if (!context) {
        const Audio = window.AudioContext || window.webkitAudioContext;
        if (!Audio) return;
        context=new Audio(); master=context.createGain();master.gain.value=.46;master.connect(context.destination);
      }
      await context.resume();
      unlocked=context.state==='running';
      await reconcile(true);
    } catch (_) {}
  }
  function save() {
    try {localStorage.setItem(key,JSON.stringify(prefs));} catch (_) {}
    reconcile();
  }
  function allOff() {
    channels.forEach(channel => prefs[channel]=false);
    stopEffects();save();
  }
  async function effect(name, duration) {
    if (!prefs.effects || !active() || !unlocked || !context) return;
    const current=scene();let url=tracksFor(current).effects?.[name];
    if(current.theme==='hall'&&name==='spin'&&duration>0&&duration<2)url='/static/hall/audio/effects/hall-spin-fast.mp3?v=calm2';
    if (!url) return;
    const run=generation;
    try {
      const data=await buffer(url);
      if (generation!==run || !prefs.effects || !active()) return;
      const source=context.createBufferSource(),gain=context.createGain();
      source.buffer=data;gain.gain.value=.6;source.connect(gain);gain.connect(master);
      if (duration>0) source.playbackRate.value=data.duration/duration;
      if(effects.size>=6){const oldest=effects.values().next().value;try{oldest.stop()}catch(_){}effects.delete(oldest)}
      effects.add(source);source.onended=()=>{effects.delete(source);source.disconnect();gain.disconnect();};source.start();
    } catch (_) {}
  }
  document.addEventListener('change',event=>{
    const channel=event.target?.dataset?.audioChannel;
    if (!channels.includes(channel)) return;
    prefs[channel]=event.target.checked === true;save();unlock();
  });
  document.getElementById('audioAllOff')?.addEventListener('click',allOff);
  document.addEventListener('pointerdown',()=>{if (!unlocked) unlock();},{passive:true});
  document.addEventListener('visibilitychange',()=>reconcile());
  new MutationObserver(()=>reconcile()).observe(root,{attributes:true,attributeFilter:['data-sky','data-halloween','data-basement','data-hall','data-hall-curtains']});
  setInterval(()=>reconcile(),1000);
  renderControls();
  window.GameAudio={allOff,effect,getState:()=>({preferences:{...prefs},scene:scene(),unlocked,
    playing:[...loops.keys()],sources:Object.fromEntries([...loops].map(([channel,playing])=>[channel,playing.url])),loaded:[...buffers.keys()],cacheBytes:[...decodedSizes.values()].reduce((a,b)=>a+b,0),effectVoices:effects.size})};
  unlock();
})();
}catch(e){console.error("[app.js] game-audio.js",e)}
;

/* ===== basement.js ===== */
try{
(() => {
 'use strict';
 const root=document.documentElement,host=document.querySelector('.bg-wide');if(!host)return;
 const scene=document.createElement('div');scene.id='basementScene';scene.setAttribute('aria-hidden','true');
 scene.innerHTML='<div id="basementWorld"><img class="basement-dim" alt="" decoding="async"><img class="basement-lit" alt="" decoding="async"></div>';
 host.appendChild(scene);
 const world=scene.firstElementChild,NS='http://www.w3.org/2000/svg';
 const button=document.getElementById('skyBtn');
 const icon=document.createElementNS(NS,'svg');icon.setAttribute('viewBox','0 0 16 16');icon.setAttribute('aria-hidden','true');icon.setAttribute('shape-rendering','crispEdges');icon.classList.add('sky-bulb');
 icon.innerHTML='<path d="M5 1h6v1h2v2h1v5h-2v3H4V9H2V4h1V2h2zM5 13h6v2H5zM6 15h4v1H6z"/><path d="M6 4h2v2H6zM5 5h1v3H5z" fill="#fff8da"/>';button?.appendChild(icon);
 const nav=document.querySelector('.tabbar');
 if(nav)for(const side of ['left','right']){const detail=document.createElement('span');detail.className='bs-nav-detail bs-nav-'+side;detail.setAttribute('aria-hidden','true');nav.appendChild(detail)}
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');
 let loaded=false,previousSky=root.dataset.sky,previousActive=root.dataset.basement==='on',flickerTimer=0,sequenceTimer=0;
 const canAnimate=()=>root.dataset.optimized!=='on'&&!reduced.matches&&!document.hidden&&window.Telegram?.WebApp?.isActive!==false;
 function clearSequence(){clearTimeout(sequenceTimer);world.classList.remove('bs-igniting','bs-flickering')}
 function sequence(element,ignition){
  element.classList.remove('bs-igniting','bs-flickering');if(!canAnimate())return;
  void element.offsetWidth;element.classList.add(ignition?'bs-igniting':'bs-flickering');
  if(element===world){clearTimeout(sequenceTimer);sequenceTimer=setTimeout(clearSequence,1300)}
  else element.addEventListener('animationend',()=>element.classList.remove('bs-igniting','bs-flickering'),{once:true});
 }
 function scheduleFlicker(){
  clearTimeout(flickerTimer);flickerTimer=0;
  if(root.dataset.basement!=='on'||root.dataset.sky==='night'||!canAnimate())return;
  flickerTimer=setTimeout(()=>{flickerTimer=0;if(root.dataset.basement==='on'&&root.dataset.sky!=='night'&&canAnimate()){sequence(world,false);window.GameAudio?.effect('lamp-flicker');scheduleFlicker()}},22000+Math.random()*26000);
 }
 window.BasementLight={preview(stage,on){stage.classList.remove('bs-igniting','bs-flickering');if(on)sequence(stage,true)}};
 function sync(){
  const active=root.dataset.basement==='on';
  if(active&&!loaded){loaded=true;for(const [selector,name]of [['.basement-lit','day'],['.basement-dim','night']]){const image=world.querySelector(selector);if(!image)continue;image.addEventListener('load',()=>dispatchEvent(new Event('resize')));}}
  if(active&&button){const dim=root.dataset.sky==='night';const label=({en:dim?'Turn light on':'Turn light off',zh:dim?'开灯':'关灯',ru:dim?'Включить свет':'Выключить свет'})[root.dataset.lang]|| (dim?'Включить свет':'Выключить свет');button.title=label;button.setAttribute('aria-label',label);button.setAttribute('aria-pressed',String(!dim));}
  scene.classList.toggle('basement-paused',document.hidden||window.Telegram?.WebApp?.isActive===false);
  nav?.classList.toggle('basement-paused',scene.classList.contains('basement-paused'));
  const sky=root.dataset.sky,changed=sky!==previousSky||active!==previousActive;
  if(!active||sky==='night'||!canAnimate())clearSequence();
  else if(changed&&previousActive&&previousSky==='night')sequence(world,true);
  if(changed||!canAnimate()||!flickerTimer)scheduleFlicker();
  previousSky=sky;previousActive=active;
 }
 new MutationObserver(sync).observe(root,{attributes:true,attributeFilter:['data-basement','data-sky','data-lang','data-optimized']});reduced.addEventListener('change',sync);

 document.addEventListener('click',event=>{
  if(root.dataset.basement!=='on')return;const target=event.target.closest('button');if(!target||target.disabled)return;
  let sound=target.matches('.kq-tab')?'shop-tab':target.matches('.shop-card')?'shop-open':target.matches('.weapon-card')?'gear-preview':target.matches('#wpApply')?'equip':target.matches('#settingsBtn')?'settings-open':target.matches('[data-cz]')?'switch':null;
  if(sound)window.GameAudio?.effect(sound);
 });
 document.addEventListener('change',event=>{if(root.dataset.basement==='on'&&event.target.matches('.pixel-switch-input'))queueMicrotask(()=>window.GameAudio?.effect('switch'))});
 document.addEventListener('visibilitychange',sync);window.Telegram?.WebApp?.onEvent?.('activated',sync);window.Telegram?.WebApp?.onEvent?.('deactivated',sync);sync();
})();
}catch(e){console.error("[app.js] basement.js",e)}
;

/* ===== authored-scenes.js ===== */
try{
(()=>{'use strict';const root=document.documentElement,host=document.querySelector('.bg-wide');if(!host)return;
 const stage=document.createElement('div');stage.id='authoredBackdrop';stage.setAttribute('aria-hidden','true');host.append(stage);
 const motion=matchMedia('(prefers-reduced-motion: reduce)'),tall=matchMedia('(max-aspect-ratio: 1/1)'),cache=new Map();let revision=0,previous=null,settleTimer=0,inFlight=false;
 const kind=()=>root.dataset.hall==='on'?'hall':root.dataset.basement==='on'?'basement':root.dataset.halloween==='on'?'halloween':'meadow';
 const url=(name)=>'/static/scenes/'+name+'.svg?v=16';
 // backgrounds uploaded by the admin ("Настройки фона"): key theme:sky:phone|pc; no entry = built-in scene
 try{window.__bgConfig=window.__bgConfig||JSON.parse(localStorage.getItem('bgConfig')||'{}')}catch(_){window.__bgConfig={}}
 const customFor=(theme,sky)=>{const row=(window.__bgConfig||{})[theme+':'+sky+':'+(tall.matches?'phone':'pc')];return row&&row.url?row.url+(row.ts?'?v='+row.ts:''):''};
 const names={meadow:{day:'meadow-day',night:'meadow-night'},halloween:{day:'halloween-nightfall-gray-calm',night:'halloween-nightfall'},basement:{day:'basement-day',night:'basement-night'}};
 async function loaded(src){
  let ready=cache.get(src);
  if(!ready){
   ready=(async()=>{const img=new Image();img.decoding='async';img.alt='';img.src=src;await new Promise((resolve,reject)=>{if(img.complete&&img.naturalWidth)return resolve();img.onload=resolve;img.onerror=reject});try{await img.decode()}catch(_){}return img})();
   cache.set(src,ready);ready.catch(()=>{if(cache.get(src)===ready)cache.delete(src)});
  }else{cache.delete(src);cache.set(src,ready)}
  while(cache.size>4)cache.delete(cache.keys().next().value);
  const template=await ready,image=template.cloneNode();try{await image.decode()}catch(_){}return image;
 }

 async function loadedAny(list){let last;for(const s of [].concat(list)){try{return await loaded(s)}catch(e){last=e}}throw last}
 async function show(src,theme,id,duration,custom){
  const image=await loadedAny(src);if(id!==revision)return false;
  image.className='authored-frame'+(custom?' authored-custom':'');image.dataset.scene=theme;image.style.opacity='0';stage.append(image);
  const old=[...stage.children].filter(e=>e!==image);for(const node of old){const alpha=getComputedStyle(node).opacity;node.style.transition='none';node.style.opacity=alpha}
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));if(id!==revision){image.remove();return false}
  for(const node of old){node.style.transition=`opacity ${duration}ms ease-in-out`;node.style.opacity='0'}image.style.transition=`opacity ${duration}ms ease-in-out`;image.style.opacity='1';
  await new Promise(resolve=>setTimeout(resolve,duration+30));if(id!==revision)return false;for(const node of old)node.remove();return true;
 }
 async function sync(){
  const theme=kind(),sky=root.dataset.sky==='night'?'night':'day',still=root.dataset.optimized==='on'||motion.matches||document.hidden;
  const curtains=root.dataset.hallCurtains==='closed'?'closed':'open',custom=customFor(theme,sky),portrait=theme==='halloween'&&tall.matches&&!custom;root.dataset.scenePortrait=portrait?'on':'off';if(previous&&theme===previous.theme&&sky===previous.sky&&still===previous.still&&curtains===previous.curtains&&portrait===previous.portrait&&custom===previous.custom)return;
  const old=previous,interrupted=inFlight;previous={theme,sky,still,curtains,portrait,custom};const id=++revision;clearTimeout(settleTimer);inFlight=true;
  const nm=theme==='hall'?'':names[theme][sky],steady=custom||(theme==='hall'?'/static/hall/room/'+sky+'-'+curtains+'.png?v=1':(()=>{const o=[];for(const m of portrait?['-m','']:[''])for(const s of still?['-still','']:[''])o.push(url(nm+m+s));o.push(url(names.halloween[sky]));return o})());
  try{
   const switchingSky=old&&old.theme===theme&&old.sky!==sky;
   if(!custom&&!(old&&old.custom)&&theme!=='hall'&&theme!=='halloween'&&switchingSky&&!still&&!interrupted){
    const duration=theme==='meadow'?9000:theme==='halloween'?3000:1300;
    const transition=theme==='meadow'?(sky==='night'?'meadow-day-to-night':'meadow-night-to-day'):theme+'-smooth-to-'+sky;
    if(!await show(url(transition),theme,id,140))return;


    settleTimer=setTimeout(()=>{if(id===revision)inFlight=false},duration);
   }else{

    const enteringHalloween=theme==='halloween'&&old&&old.theme!==theme&&!still;
    if(enteringHalloween)stage.classList.add('scene-glitch');
    if(!await show(steady,theme,id,motion.matches?0:still?140:enteringHalloween?100:old?650:0,!!custom))return;
    stage.classList.remove('scene-glitch');if(id===revision)inFlight=false;
   }
  }catch(_){if(id===revision){inFlight=false;previous=null}}
 }
 let scheduled=false;function schedule(){if(!scheduled){scheduled=true;queueMicrotask(()=>{scheduled=false;sync()})}}
 new MutationObserver(schedule).observe(root,{attributes:true,attributeFilter:['data-hall','data-hall-curtains','data-theme','data-sky','data-halloween','data-basement','data-optimized']});motion.addEventListener('change',schedule);tall.addEventListener('change',schedule);addEventListener('bgconfig',schedule);document.addEventListener('visibilitychange',schedule);
 window.SceneBackground={get state(){return previous},get transitioning(){return inFlight},refresh:schedule};schedule();
})();
}catch(e){console.error("[app.js] authored-scenes.js",e)}
;

/* ===== hall/hall-room-fx.js ===== */
class HallRoomFX {
 constructor(canvas,{optimized=false}={}){this.canvas=canvas;this.g=canvas.getContext('2d');this.optimized=optimized;this.particles=[];this.last=0;this.emitted=0;this.raf=0;this.flickerUntil=0;this.destroyed=false;this.wicks=[[528,49],[571,25],[674,25],[731,56],[180,224],[296,248],[455,273],[470,269],[478,277],[422,490],[1187,274],[1195,269],[1209,279],[1395,246],[1414,239],[1617,178],[1639,165]];this.resize=()=>{const r=canvas.getBoundingClientRect(),d=Math.min(devicePixelRatio||1,2,Math.sqrt(2000000/Math.max(1,r.width*r.height)));canvas.width=Math.max(1,Math.round(r.width*d));canvas.height=Math.max(1,Math.round(r.height*d))};this.ro=new ResizeObserver(this.resize);this.ro.observe(canvas);this.visibility=()=>{if(document.hidden){cancelAnimationFrame(this.raf);this.raf=0}else this.resume()};document.addEventListener('visibilitychange',this.visibility);this.resume()}
 setOptimized(v){this.optimized=!!v;this.particles=[];if(v){cancelAnimationFrame(this.raf);this.raf=0;this.g.clearRect(0,0,this.canvas.width,this.canvas.height)}else this.resume()}
 flicker(){this.flickerUntil=performance.now()+650}
 resume(){if(this.raf||this.optimized||document.hidden||this.destroyed)return;const frame=now=>{this.raf=0;if(this.optimized||document.hidden||this.destroyed)return;if(now-this.last<1000/30){this.raf=requestAnimationFrame(frame);return}this.last=now;const g=this.g,w=this.canvas.width,h=this.canvas.height,scale=Math.max(w/1672,h/941),ox=(w-1672*scale)/2,oy=(h-941*scale)/2;g.clearRect(0,0,w,h);g.save();g.translate(ox,oy);g.scale(scale,scale);
 if(now-this.emitted>190&&this.particles.length<18){this.emitted=now;this.particles.push({x:1480+Math.random()*75,y:535+Math.random()*20,born:now,life:1000+Math.random()*800,dx:(Math.random()-.5)*30})}
 for(const p of this.particles){const t=(now-p.born)/p.life;if(t>1)continue;g.globalAlpha=(1-t)*.7;g.fillStyle=t<.4?'#ffd077':'#ec763c';g.fillRect(p.x+p.dx*t,p.y-t*100,2,3)}g.globalAlpha=1;this.particles=this.particles.filter(p=>now-p.born<p.life);
 this.wicks.forEach(([x,y],i)=>{const pulse=.15+.06*Math.sin(now/(130+i*5)+i)+.03*Math.sin(now/57+i);const a=now<this.flickerUntil?pulse*(.3+.7*Math.sin(now/31+i)**2):pulse;const grad=g.createRadialGradient(x,y-8,0,x,y-8,24);grad.addColorStop(0,`rgba(255,207,109,${a})`);grad.addColorStop(1,'rgba(255,176,70,0)');g.fillStyle=grad;g.fillRect(x-24,y-32,48,48)});g.restore();this.raf=requestAnimationFrame(frame)};this.raf=requestAnimationFrame(frame)}
 destroy(){this.destroyed=true;cancelAnimationFrame(this.raf);this.ro.disconnect();document.removeEventListener('visibilitychange',this.visibility)}
}
window.HallRoomFX=HallRoomFX;
;

/* ===== hall/hall-live.js ===== */
try{
(()=>{'use strict';const root=document.documentElement,host=document.querySelector('.bg-wide'),wrap=document.querySelector('.wheel-wrap'),sky=document.getElementById('skyBtn');if(!host||!wrap||!sky)return;
 const active=()=>root.dataset.hall==='on',optimized=()=>root.dataset.optimized==='on'||matchMedia('(prefers-reduced-motion: reduce)').matches;
 const control=document.createElement('button');control.id='hallCurtains';control.type='button';control.innerHTML='<img alt="" width="24" height="24">';wrap.append(control);
 const light=document.createElement('img');light.className='hallSkyIcon';light.alt='';light.width=light.height=24;sky.append(light);
 const canvas=document.createElement('canvas');canvas.id='hallRoomFx';canvas.setAttribute('aria-hidden','true');host.append(canvas);const room=new HallRoomFX(canvas,{optimized:true});let projection=null,timer=0,previousSky=root.dataset.sky;
 try{root.dataset.hallCurtains=localStorage.getItem('hallCurtains')==='closed'?'closed':'open'}catch(_){root.dataset.hallCurtains='open'}
 control.onclick=e=>{e.stopPropagation();if(!active())return;const closed=root.dataset.hallCurtains!=='closed';root.dataset.hallCurtains=closed?'closed':'open';try{localStorage.setItem('hallCurtains',closed?'closed':'open')}catch(_){}window.GameAudio?.effect(closed?'curtains-close':'curtains-open')};
 function layout(){if(!active())return;const b=host.getBoundingClientRect(),w=wrap.getBoundingClientRect(),hat=document.getElementById('centerHat'),goal=hat?.hidden?document.getElementById('hatQuestion'):hat,g=goal?.getBoundingClientRect();if(!b.width||!b.height)return;
  let cx=b.width/2,cy=b.height*.61,ww=Math.min(b.width*.88,460);
  if(w.width&&g?.width){cx=g.x+g.width/2-b.x;cy=g.bottom-b.y;ww=w.width}else if(projection){cx=projection.contactX/projection.hostWidth*b.width;cy=projection.contactY/projection.hostHeight*b.height;ww=projection.wheelWidth/projection.hostWidth*b.width}
  const s=Math.max(b.width/1672,b.height/941,ww/570,cy/595,(b.height-cy)/346),x=cx-836*s,y=cy-595*s;
  projection={x,y,scale:s,contactX:cx,contactY:cy,hostWidth:b.width,hostHeight:b.height,wheelWidth:ww};for(const [key,value]of Object.entries({'--hall-x':x+'px','--hall-y':y+'px','--hall-w':1672*s+'px','--hall-h':941*s+'px'}))host.style.setProperty(key,value);
 }
 function scheduleFlicker(){if(!active()||optimized()||document.hidden){clearTimeout(timer);timer=0;return}if(timer)return;timer=setTimeout(()=>{timer=0;if(active()&&!optimized()&&!document.hidden){room.flicker();scheduleFlicker()}},19000+Math.random()*19000)}
 function sync(){const on=active(),night=root.dataset.sky==='night',closed=root.dataset.hallCurtains==='closed';control.hidden=!on;room.setOptimized(!on||optimized());for(const id of ['arcWin','arcLose']){const el=document.getElementById(id);el.setAttribute('r',on?'105.5':'120');el.setAttribute('pathLength',String(2*Math.PI*120))}if(on){light.src='/static/hall/ui/light-'+(night?'off':'on')+'.png';control.firstChild.src='/static/hall/ui/curtains-'+(closed?'closed':'open')+'.png';control.title=closed?'Открыть шторы':'Закрыть шторы';control.setAttribute('aria-label',control.title);control.setAttribute('aria-pressed',String(closed));sky.title=night?'Включить день':'Включить ночь';sky.setAttribute('aria-label',sky.title);if(previousSky!==root.dataset.sky)queueMicrotask(()=>window.GameAudio?.effect(night?'light':'light-on'));layout()}previousSky=root.dataset.sky;scheduleFlicker()}
 new MutationObserver(sync).observe(root,{attributes:true,attributeFilter:['data-hall','data-sky','data-hall-curtains','data-optimized']});new ResizeObserver(layout).observe(wrap);new ResizeObserver(layout).observe(host);document.getElementById('centerHat')?.addEventListener('load',layout);new MutationObserver(()=>requestAnimationFrame(layout)).observe(document.getElementById('view-upgrade'),{attributes:true,attributeFilter:['hidden']});window.addEventListener('resize',layout);document.addEventListener('visibilitychange',sync);

 const preview=document.getElementById('tpStage');new MutationObserver(()=>{const pic=preview?.querySelector('.tc-pic[data-theme="hall"]');if(!pic||pic.dataset.locked==='true'||preview.querySelector('.hall-preview-controls'))return;let night=false,closed=false;const box=document.createElement('div');box.className='hall-preview-controls';for(const kind of ['sky','curtains']){const b=document.createElement('button');b.type='button';const i=document.createElement('img');i.src='/static/hall/ui/'+(kind==='sky'?'light-on':'curtains-open')+'.png';i.alt='';b.append(i);b.title=kind==='sky'?'Включить ночь':'Закрыть шторы';b.setAttribute('aria-label',b.title);b.onclick=()=>{if(kind==='sky')night=!night;else closed=!closed;pic.querySelector('img').src='/static/hall/room/'+(night?'night':'day')+'-'+(closed?'closed':'open')+'.png';i.src='/static/hall/ui/'+(kind==='sky'?'light-'+(night?'off':'on'):'curtains-'+(closed?'closed':'open'))+'.png';b.title=kind==='sky'?(night?'Включить день':'Включить ночь'):(closed?'Открыть шторы':'Закрыть шторы');b.setAttribute('aria-label',b.title)};box.append(b)}preview.append(box)}).observe(preview,{childList:true,subtree:true});
 document.addEventListener('click',e=>{if(!active())return;const b=e.target.closest('button');if(!b||b.disabled)return;const sound=b.matches('.kq-tab')?'shop-tab':b.matches('.shop-card')?'shop-open':b.matches('.weapon-card')?'gear-preview':b.matches('#wpApply')?'equip':b.matches('#settingsBtn')?'settings-open':null;if(sound)window.GameAudio?.effect(sound)});
 function spinPointer(pointer,from,target,fast){const quick=fast||optimized(),ms=quick?1300:4020,end=from+(quick?3:6)*360+((target-from+360)%360);wrap.classList.add('hall-charging');window.GameAudio?.effect('spin-start');pointer.classList.remove('spinning');pointer.style.transform=`rotate(${from}deg)`;let animation;
  try{animation=pointer.animate([{transform:`rotate(${from}deg)`,offset:0,easing:'ease-in-out'},{transform:`rotate(${from-7}deg)`,offset:.1,easing:'cubic-bezier(.12,.62,.08,1)'},{transform:`rotate(${end}deg)`,offset:1}],{duration:ms,fill:'forwards'})}catch(_){pointer.style.transform=`rotate(${end}deg)`}
  setTimeout(()=>wrap.classList.remove('hall-charging'),quick?130:420);setTimeout(()=>{pointer.style.transform=`rotate(${end}deg)`;animation?.cancel();if(active()){wrap.classList.add('hall-settle');setTimeout(()=>wrap.classList.remove('hall-settle'),500);window.GameAudio?.effect('spin-stop')}},ms);return{deg:end,ms}
 }
 window.HallLive={spinPointer,layout,get projection(){return projection}};sync();
})();
}catch(e){console.error("[app.js] hall/hall-live.js",e)}
;

/* ===== app-viewport.js ===== */
try{
(()=>{'use strict';let connected=null,requested=false;const root=document.documentElement;
 function safe(){const app=window.Telegram?.WebApp;if(!app)return;for(const edge of ['top','bottom','left','right']){const system=Math.max(0,Number(app.safeAreaInset?.[edge])||0),content=Math.max(0,Number(app.contentSafeAreaInset?.[edge])||0);root.style.setProperty('--app-inset-'+edge,(system+content)+'px')}root.dataset.fullscreen=app.isFullscreen?'on':'off'}
 function connect(){const app=window.Telegram?.WebApp;if(!app)return;const native=!!app.initData||!['unknown','weba','webk','web'].includes(app.platform||'unknown');try{app.expand?.()}catch(_){}if(connected!==app){connected=app;for(const event of ['safeAreaChanged','contentSafeAreaChanged','fullscreenChanged','viewportChanged'])try{app.onEvent?.(event,safe)}catch(_){}}
  safe();if(native&&!requested&&!app.isFullscreen&&app.requestFullscreen&&(!app.isVersionAtLeast||app.isVersionAtLeast('8.0'))){requested=true;try{app.requestFullscreen()}catch(_){}}
 }
 window.GameViewport={connect,safe};connect();document.getElementById('telegramSdk')?.addEventListener('load',connect);

 if(!window.Telegram?.WebApp?.initData)document.addEventListener('pointerdown',()=>{const app=window.Telegram?.WebApp;if(app?.initData)return;if(!document.fullscreenElement&&document.fullscreenEnabled)try{document.documentElement.requestFullscreen?.().catch(()=>{})}catch(_){}},{once:true});
})();
}catch(e){console.error("[app.js] app-viewport.js",e)}
;

/* ===== personal-boss.js ===== */
try{(function(){
'use strict';
// Personal boss on the player side: spawn notice with rules, HP bar the skeleton hangs on, countdown,
// hit / death animations and the reward window. Data: state.personal_boss and /api/state/personal-boss.
(() => {
 // the game script runs in a closure; it hands this file what it needs as window.HatDrop (end of the game script in index.html)
 const HD = window.HatDrop;
 if (!HD) return;
 const T = (s, v) => { try { return HD.tr(s, v); } catch (_) { return s; } };
 const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
 const num = (n, d = 2) => { try { return HD.fmt(n, d); } catch (_) { return (+n).toFixed(d); } };
 const busyGame = () => { try { return HD.busy(); } catch (_) { return false; } };
 const otherModal = () => [...document.querySelectorAll('.modal:not([hidden])')].some((m) => !m.classList.contains('pb-modal'));
 const reduced = () => document.documentElement.dataset.optimized === 'on' || matchMedia('(prefers-reduced-motion: reduce)').matches;

 // ---------- pixel art (viewBox 0 0 76 100 = 38x50 cells of 2 units; the bar top sits at y=38) ----------
 const PAL = { K: '#22140c', W: '#efe4c8', S: '#bfae86', D: '#1a0d07', E: '#ff9a2a', Y: '#fff3b0', L: '#fffaf0' };
 const sprite = (rows, ox, oy, px = 2) => rows.map((row, r) => {
  let out = '';
  for (let i = 0; i < row.length;) {
   const c = row[i]; let j = i; while (j < row.length && row[j] === c) j++;
   if (c !== '.') out += `<rect${c === 'E' || c === 'Y' ? ' class="pb-eye"' : ''} x="${ox + i * px}" y="${oy + r * px}" width="${(j - i) * px}" height="${px}" fill="${PAL[c]}"/>`;
   i = j;
  }
  return out;
 }).join('');
 const SKULL = ['....KKKKKK....', '..KKWWWWWWKK..', '.KWLLWWWWWWWK.', 'KWLWWWWWWWWWSK', 'KWWWWWWWWWWWSK', 'KWDDDDWWDDDDSK', 'KWDEEDWWDEEDSK',
  'KWDEYDWWDYEDSK', 'KWDDDDWWDDDDSK', 'KSWWWWKKWWWWSK', '.KSWWWKKWWWSK.', '.KSSWWWWWWSSK.', '..KWKWKWKWKWK.'];
 const JAW = ['KWKWKWKWKWKK', 'KSWWWWWWWWSK', '.KSSWWWWSSK.', '..KKKKKKKK..'];
 const CRACK = ['K.', '.K', 'K.', '.K'];
 const TORSO = ['.KKKKKKKKKKKKKKKK.', 'KWWWWWWWWWWWWWWWWK', '.KKKKKKKWWKKKKKKK.', '..KWWWWKWWKWWWWK..', '.KWKKKKKWWKKKKKWK.', '.KWK...KWWK...KWK.',
  '..KWWWWKWWKWWWWK..', '.KWKKKKKWWKKKKKWK.', '.KWK...KWWK...KWK.', '..KWWWWKWWKWWWWK..', '...KKKKKWWKKKKK...', '.......KWWK.......', '.......KWWK.......',
  '....KKKKWWKKKK....', '...KWWWWWWWWWWK...', '...KWDDWWWWDDWK...', '....KWWK..KWWK....', '.....KK....KK.....'];
 const LEGS = ['..KWK..KWK..', '..KWK..KWK..', '..KWK..KWK..', '..KWK..KWK..', '.KWWK..KWWK.', '..KWK..KWK..', '..KWK..KWK..', '..KWK..KWK..',
  '..KWK..KWK..', '.KWWK..KWWK.', 'KWWWK..KWWWK', 'KKKKK..KKKKK'];
 const ARM = ['..K.K.K....', '..KWKWKWK..', '..KWWWWWK..', '...KWWWK...', '....KWK....', '....KWK....', '....KWK....', '....KWWK...', '.....KWWK..',
  '......KWWK.', '.......KWWK', '........KWK', '........KWK', '........KWK'];
 const mirror = (rows) => rows.map((r) => [...r].reverse().join(''));
 const HAND = ['..KKKKK..', '.KWWWWWK.', 'KWWSWSWWK', 'KWKWKWKWK', 'KWKWKWKWK', 'KWKWKWKWK', '.K.K.K.K.'];
 function skeleton(cls, withArms = false, viewBox = '0 0 76 100') {
  return `<svg class="${cls} pb-skel" viewBox="${viewBox}" aria-hidden="true" shape-rendering="crispEdges">
<g class="pb-legs">${sprite(LEGS, 26, 74)}</g>
<g class="pb-torso">${sprite(TORSO, 20, 38)}</g>
${withArms ? `<g class="pb-armsbig">${sprite(ARM, 0, 12)}${sprite(mirror(ARM), 54, 12)}</g>` : ''}
<g class="pb-head">${sprite(SKULL, 24, 4)}<g class="pb-crack">${sprite(CRACK, 42, 6)}</g></g>
<g class="pb-jaw">${sprite(JAW, 26, 30)}</g>
</svg>`;
 }
 const HANDS = `<svg class="pb-hands" viewBox="0 0 96 18" aria-hidden="true" shape-rendering="crispEdges"><g>${sprite(HAND, 9, 0)}</g><g>${sprite(HAND, 69, 0)}</g></svg>`;

 // ---------- state ----------
 let view = null, skew = 0, lastId = '', lastRemaining = null, introFor = '', resultFor = '', dyingFor = '', pollTimer = 0, polling = false, hudShown = null;

 const left = () => view ? Math.max(0, view.end - (Date.now() / 1000 + skew)) : 0;
 const clock = (s) => { s = Math.ceil(s); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return (h ? h + ':' + String(m).padStart(2, '0') : String(m).padStart(2, '0')) + ':' + String(x).padStart(2, '0'); };
 const durationText = (v) => { const m = Math.round((v.end - v.start) / 60); return m % 60 === 0 ? (m === 60 ? T('1 час') : T('{n} ч', { n: m / 60 })) : T('{n} мин', { n: m }); };
 const rateText = (v) => { const u = +(v.rates?.upgrade ?? 1), c = +(v.rates?.chests ?? 1); return u === 1 && c === 1 ? T('1 GRAM ставки = 1 HP урона') : T('1 GRAM ставки = 1 HP урона (апгрейды ×{u}, сундуки ×{c})', { u, c }); };

 function hud() {
  let node = document.getElementById('pbHud');
  if (node) return node;
  const host = document.getElementById('view-upgrade');
  if (!host) return null;
  node = document.createElement('div');
  node.id = 'pbHud'; node.hidden = true;
  node.innerHTML = `<div class="pb-row"><span class="pb-title">☠ ${esc(T('Личный босс'))}</span><span class="pb-timer"></span></div>${skeleton('pb-body')}<div class="pb-bar" role="progressbar" aria-label="${esc(T('HP личного босса'))}" aria-valuemin="0"><i class="pb-ghost"></i><i class="pb-fill"></i><span class="pb-hp"></span></div>${HANDS}<button class="pb-info" type="button" aria-label="${esc(T('Правила личного босса'))}">?</button>`;
  node.querySelector('.pb-info').onclick = () => view && openIntro(view, true);
  const live = document.getElementById('bossLiveHud');
  if (live && live.parentNode === host) live.after(node); else host.prepend(node);
  return node;
 }
 function chip() {
  let node = document.getElementById('pbChip');
  if (node) return node;
  node = document.createElement('button');
  node.id = 'pbChip'; node.type = 'button'; node.hidden = true;
  node.innerHTML = `${skeleton('pb-chip-skull', false, '20 2 36 38')}<span><b>${esc(T('Личный босс'))}</b><br><span class="pb-chip-time"></span></span>`;
  node.onclick = () => { try { HD.showView('upgrade'); } catch (_) {} };
  document.body.append(node);
  return node;
 }
 function setHudVisible(on) {
  const node = hud(); if (!node) return;
  if (node.hidden === !on && hudShown === on) return;
  node.hidden = !on; hudShown = on;
  try { HD.fitUpgrade(); } catch (_) {}
 }

 function paintBar(v) {
  const node = hud(); if (!node) return;
  const frac = v.hp > 0 ? Math.max(0, Math.min(1, v.remaining / v.hp)) : 0;
  node.querySelector('.pb-fill').style.transform = `scaleX(${frac})`;
  node.querySelector('.pb-ghost').style.transform = `scaleX(${frac})`;
  node.querySelector('.pb-hp').textContent = `${num(v.remaining, 2)} / ${num(v.hp, 0)} HP`;
  const bar = node.querySelector('.pb-bar'); bar.setAttribute('aria-valuemax', v.hp); bar.setAttribute('aria-valuenow', v.remaining);
  node.classList.toggle('low', frac < .3);
  node.querySelector('.pb-title').textContent = v.name || T('Скелет');
 }

 function playHit(amount) {
  const node = hud(); if (!node || node.hidden) return;
  node.classList.remove('hit'); void node.offsetWidth; node.classList.add('hit');
  setTimeout(() => node.classList.remove('hit'), 420);
  const pop = document.createElement('span'); pop.className = 'pb-dmg'; pop.textContent = '−' + num(amount, 2) + ' HP';
  node.append(pop); setTimeout(() => pop.remove(), 1200);
  try { HD.haptic('impact', 'light'); } catch (_) {}
 }

 function tick() {
  const node = document.getElementById('pbHud'), c = document.getElementById('pbChip');
  if (!view || view.status !== 'active') { if (c) c.hidden = true; return; }
  const s = left(), text = clock(s);
  if (node) { const t = node.querySelector('.pb-timer'); t.textContent = '⏳ ' + text; t.classList.toggle('urgent', s < 300); }
  document.querySelectorAll('[data-pb-left]').forEach((e) => { e.textContent = text; });
  const onUpgrade = !document.getElementById('view-upgrade')?.hidden;
  const box = chip(); box.hidden = onUpgrade || otherModal(); box.querySelector('.pb-chip-time').textContent = text;
  if (s <= 0) poll(true);
 }

 // ---------- modals ----------
 function modal(id, cls, inner) {
  document.getElementById(id)?.remove();
  const node = document.createElement('div');
  node.id = id; node.className = `modal pb-modal ${cls}`; node.setAttribute('role', 'dialog'); node.setAttribute('aria-modal', 'true');
  node.innerHTML = `<div class="modal-card">${inner}</div>`;
  document.body.append(node);
  return node;
 }
 const award = (a, i) => `<div class="pb-award" style="--i:${i}">${a.mystery ? '<span class="pb-mystery" aria-hidden="true">?</span>' : `<img src="${esc(a.image)}" alt="">`}<span>${esc(a.name)}</span>${a.value != null ? `<small>≈ ${esc(num(a.value, 2))} GRAM</small>` : ''}${a.already ? `<small>${esc(T('уже в коллекции'))}</small>` : ''}</div>`;
 // the gift is a surprise until the boss falls (the result window shows what dropped)
 const rewardCards = (v) => [{ name: T('Случайный подарок'), mystery: true }, ...(v.hand ? [{ name: v.hand.name, image: v.hand.image }] : [])].map(award).join('');

 // each child of the card fades in one after another (--n)
 const stagger = (node) => [...node.querySelector('.modal-card').children].forEach((el, i) => el.style.setProperty('--n', i));

 function openIntro(v, rules = false) {
  introFor = v.id;
  const node = modal('pbIntro', 'pb-intro', `
   <div class="pb-top">
    <span class="pb-tag">☠ ${esc(T('Личный босс'))}</span>
    <h2>${esc(rules ? T('Правила личного босса') : (v.name || T('Скелет')))}</h2>
    <p class="pb-lead">${esc(rules ? T('Как победить босса') : T('Пришёл только за тобой — у других игроков его нет.'))}</p>
   </div>
   <div class="pb-stats">
    <div><small>${esc(T('Здоровье'))}</small><b>${esc(num(v.hp, 0))} HP</b></div>
    <div><small>${esc(T('Осталось'))}</small><b data-pb-left>${clock(left())}</b></div>
   </div>
   <ol class="pb-steps">
    <li>${esc(T('Делай ставки в апгрейдах и сундуках — каждая бьёт босса.'))} ${esc(rateText(v))}.</li>
    <li>${esc(T('Победи его за {time} — иначе он уйдёт вместе с наградой.', { time: durationText(v) }))}</li>
    <li>${esc(T('Здоровье и таймер видны над колесом апгрейда.'))}</li>
   </ol>
   <div class="pb-label">${esc(T('Награда за победу'))}</div>
   <div class="pb-awards">${rewardCards(v)}</div>
   <div class="pb-actions"><button class="cta" type="button" data-pb-go>${esc(rules ? T('Понятно') : T('В бой!'))}</button></div>`);
  stagger(node);
  node.querySelector('[data-pb-go]').onclick = async () => {
   node.remove();
   if (!v.intro_seen) { v.intro_seen = true; try { await HD.api('/api/personal-boss/ack', { id: v.id, kind: 'intro' }); } catch (_) {} }
   try { HD.showView('upgrade'); } catch (_) {}
  };
  if (!rules) { try { HD.haptic('notification', 'warning'); } catch (_) {} }
  node.querySelector('[data-pb-go]').focus();
  node.querySelector('.modal-card').scrollTop = 0;
 }

 function openResult(v) {
  resultFor = v.id;
  const won = v.status === 'defeated';
  const node = modal('pbResult', won ? 'pb-win' : 'pb-gone', won ? `
   <div class="pb-top">
    <span class="pb-tag">${esc(T('Победа'))}</span>
    <h2>${esc(T('Босс повержен!'))}</h2>
    <p class="pb-lead">${esc(T('Награды уже твои: подарок — в инвентаре, снаряжение — в коллекции.'))}</p>
   </div>
   <div class="pb-label">${esc(T('Тебе выпало'))}</div>
   <div class="pb-awards">${(v.awards || []).map(award).join('')}</div>
   <div class="pb-actions"><button class="cta" type="button" data-pb-claim>${esc(T('Забрать'))}</button></div>` : `
   <div class="pb-top">
    <span class="pb-tag">${esc(T('Время вышло'))}</span>
    <h2>${esc(T('Босс ушёл'))}</h2>
    <p class="pb-lead">${esc(T('Он скрылся вместе с наградой. Следующий личный босс появится в случайный момент.'))}</p>
   </div>
   <div class="pb-actions"><button class="cta" type="button" data-pb-claim>${esc(T('Понятно'))}</button></div>`);
  stagger(node);
  const button = node.querySelector('[data-pb-claim]');
  button.onclick = async () => {
   button.disabled = true;
   try {
    const r = await HD.api('/api/personal-boss/ack', { id: v.id, kind: 'result' });
    node.remove(); view = r.personal_boss; if (HD.state) HD.state.personal_boss = view;
    if (won) { try { await HD.refresh(); } catch (_) {} }
   } catch (_) { button.disabled = false; try { HD.toast(T('Не удалось подтвердить. Попробуйте ещё раз.')); } catch (__) {} }
  };
  try { HD.haptic('notification', won ? 'success' : 'error'); } catch (_) {}
  button.focus();
  node.querySelector('.modal-card').scrollTop = 0;
 }

 function finishInHud(v) {
  dyingFor = v.id;
  const node = hud();
  const onUpgrade = node && !document.getElementById('view-upgrade')?.hidden && !node.hidden;
  if (!onUpgrade || reduced()) { setHudVisible(false); openResult(v); return; }
  paintBar({ ...v, remaining: 0 });
  node.classList.add('dying');
  setTimeout(() => { node.classList.remove('dying'); setHudVisible(false); openResult(v); }, 1750);
 }

 // ---------- main render ----------
 function render(v, fresh = true) {
  if (v && fresh && v.now) skew = v.now - Date.now() / 1000;
  view = v || null;
  if (!view) { setHudVisible(false); tick(); schedule(); return; }
  if (view.status === 'active') {
   hud();
   if (!document.getElementById('pbHud')?.classList.contains('dying')) setHudVisible(true);
   paintBar(view);
   if (lastId === view.id && lastRemaining != null && view.remaining < lastRemaining - 1e-9) playHit(lastRemaining - view.remaining);
   if (!view.intro_seen && introFor !== view.id) {
    if (!otherModal() && !busyGame()) openIntro(view);
   }
  } else if (resultFor !== view.id && dyingFor !== view.id) {
   if (busyGame() || otherModal()) setTimeout(() => { if (view && view.id === v.id) render(view, false); }, 600);
   else if (view.status === 'defeated') finishInHud(view);
   else { setHudVisible(false); openResult(view); }
  }
  lastId = view.id; lastRemaining = view.status === 'active' ? view.remaining : 0;
  tick(); schedule();
 }

 async function poll(now = false) {
  if (polling || (document.hidden && !now)) return schedule();
  polling = true;
  try { const r = await HD.api('/api/state/personal-boss'); if (HD.state) HD.state.personal_boss = r.personal_boss; render(r.personal_boss); }
  catch (_) { schedule(); }
  finally { polling = false; }
 }
 function schedule() {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(poll, view && view.status === 'active' ? 4000 : 20000);
 }

 // the game calls this after every state render (refresh() after every round)
 HD.onState = (s) => { try { if (s && 'personal_boss' in s) render(s.personal_boss); } catch (e) { console.error(e); } };
 setInterval(tick, 1000);
 document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(true); });
 try { const s = HD.state; if (s && 'personal_boss' in s) render(s.personal_boss); else poll(true); } catch (_) { poll(true); }
})();
})()}catch(e){console.error("[app.js] personal-boss.js",e)}
;

/* ===== deposit-ux.js ===== */
try{(function(){
'use strict';
// Deposit and gift-deposit windows: X button, closing animation, gifts appearing one by one.
(() => {
  const CLOSE_MS = 220;
  const closers = { depositModal: 'depositCloseBtn', giftModal: 'giftCloseBtn' };
  let passing = false;

  function animateThen(modal, run) {
    if (modal.classList.contains('dux-closing')) return;
    modal.classList.add('dux-closing');
    setTimeout(() => {
      modal.classList.remove('dux-closing');
      passing = true;
      try { run(); } finally { passing = false; }
    }, CLOSE_MS);
  }

  // Let the existing close handlers run only after the closing animation.
  document.addEventListener('click', (e) => {
    if (passing) return;
    const t = e.target;
    for (const [modalId, btnId] of Object.entries(closers)) {
      const modal = document.getElementById(modalId);
      if (!modal || modal.hidden) continue;
      const btn = document.getElementById(btnId);
      const isX = t.closest && t.closest('.dux-x') && modal.contains(t);
      if (isX || (btn && t === btn) || t === modal) {
        e.preventDefault();
        e.stopImmediatePropagation();
        animateThen(modal, () => { if (btn) btn.click(); else modal.hidden = true; });
        return;
      }
    }
  }, true);

  function addX(modalId) {
    const card = document.querySelector('#' + modalId + ' .modal-card');
    if (!card || card.querySelector('.dux-x')) return;
    const x = document.createElement('button');
    x.type = 'button';
    x.className = 'dux-x';
    x.setAttribute('aria-label', 'Закрыть');
    x.textContent = '✕';
    card.prepend(x);
  }

  function decorate(list) {
    const items = list.querySelectorAll('.gift-item:not([data-dux])');
    let i = list.querySelectorAll('.gift-item[data-dux]').length;
    for (const item of items) {
      item.dataset.dux = '1';
      item.style.setProperty('--dux-i', String(Math.min(i++, 24)));
      const img = item.querySelector('img');
      if (img) {
        if (img.complete && img.naturalWidth) img.classList.add('dux-loaded');
        else img.addEventListener('load', () => img.classList.add('dux-loaded'), { once: true });
      }
    }
  }

  function skeletons(list) {
    if (list.querySelector('.gift-item, .dux-skel')) return;
    for (let i = 0; i < 6; i++) {
      const s = document.createElement('div');
      s.className = 'dux-skel';
      list.appendChild(s);
    }
  }

  function init() {
    Object.keys(closers).forEach(addX);
    const list = document.getElementById('giftList');
    if (!list) return;
    let loadingText = null;
    new MutationObserver(() => {
      const note = list.querySelector('.gift-empty');
      // Placeholders stay while only the "loading" note is shown.
      if (list.querySelector('.gift-item') || !note || note.textContent !== loadingText) {
        list.querySelectorAll('.dux-skel').forEach((s) => s.remove());
        loadingText = null;
      }
      decorate(list);
    }).observe(list, { childList: true, subtree: true, characterData: true });
    const modal = document.getElementById('giftModal');
    new MutationObserver(() => {
      if (modal.hidden) return;
      const note = list.querySelector('.gift-empty');
      if (note && !list.querySelector('.gift-item')) {
        loadingText = note.textContent;
        skeletons(list);
      }
    }).observe(modal, { attributes: true, attributeFilter: ['hidden'] });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
})()}catch(e){console.error("[app.js] deposit-ux.js",e)}
;

/* ===== ui-fixes.js ===== */
try{(function(){
'use strict';
// Desktop helpers: Esc closes the top dialog.
(() => {
  const CLOSE_RE = /^(закрыть|понятно|close|ok|отмена)$/i;

  function topModal() {
    const open = [...document.querySelectorAll('.modal:not([hidden])')];
    if (!open.length) return null;
    open.sort((a, b) => (parseInt(getComputedStyle(a).zIndex, 10) || 0) - (parseInt(getComputedStyle(b).zIndex, 10) || 0));
    return open[open.length - 1];
  }

  function closeButton(modal) {
    const x = modal.querySelector('.dux-x');
    if (x) return x;
    const byId = [...modal.querySelectorAll('button[id]')].find((b) => /close/i.test(b.id) && !b.disabled);
    if (byId) return byId;
    return [...modal.querySelectorAll('button')].reverse().find((b) => !b.disabled && CLOSE_RE.test(b.textContent.trim()));
  }

  // Tap the chance (or the spin cost) under the wheel to type your own chance.
  function chanceLimits() {
    const num = (id, d) => parseInt(((document.getElementById(id) || {}).textContent || '').replace(/\D/g, ''), 10) || d;
    return [num('chanceMin', 1), num('chanceMax', 70)];
  }

  function openChanceDialog() {
    const input = document.getElementById('chanceInput');
    if (!input || input.disabled) return;
    const [min, max] = chanceLimits();
    let modal = document.getElementById('chanceModal');
    if (!modal) {
      modal = document.createElement('div');
      modal.className = 'modal'; modal.id = 'chanceModal'; modal.hidden = true;
      modal.innerHTML = '<section class="modal-card chance-card" role="dialog" aria-modal="true" aria-labelledby="chanceModalTitle">'
        + '<h2 id="chanceModalTitle">Свой шанс</h2><p class="chance-hint"></p>'
        + '<div class="chance-field"><input type="number" inputmode="numeric" step="1" id="chanceModalInput"><span>%</span></div>'
        + '<p class="chance-error" hidden></p>'
        + '<button class="cta" type="button" id="chanceModalOk">Применить</button>'
        + '<button class="ghost" type="button" id="chanceModalClose">Закрыть</button></section>';
      document.body.appendChild(modal);
      const field = modal.querySelector('#chanceModalInput'), err = modal.querySelector('.chance-error');
      const close = () => { modal.hidden = true; };
      const apply = () => {
        const [lo, hi] = chanceLimits();
        const v = Number(field.value);
        if (!Number.isInteger(v) || v < lo || v > hi) {
          err.textContent = `Введите целое число от ${lo} до ${hi}`; err.hidden = false; field.focus(); return;
        }
        input.value = String(v);
        input.dispatchEvent(new Event('change', { bubbles: true }));
        close();
      };
      modal.querySelector('#chanceModalOk').addEventListener('click', apply);
      modal.querySelector('#chanceModalClose').addEventListener('click', close);
      field.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); apply(); } });
      field.addEventListener('input', () => { err.hidden = true; });
      modal.addEventListener('click', (e) => { if (e.target === modal) close(); });
    }
    const field = modal.querySelector('#chanceModalInput');
    field.min = String(min); field.max = String(max);
    field.value = parseInt((document.getElementById('modeChance') || {}).textContent, 10) || '';
    modal.querySelector('.chance-hint').textContent = `От ${min}% до ${max}%. Чем выше шанс, тем дороже прокрут.`;
    modal.querySelector('.chance-error').hidden = true;
    modal.hidden = false;
    setTimeout(() => { field.focus(); field.select(); }, 50);
  }

  document.addEventListener('click', (e) => {
    if (e.target.closest && e.target.closest('#modeChance, .mode-tag.mode-cost')) openChanceDialog();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || e.defaultPrevented) return;
    const modal = topModal();
    if (!modal) return;
    const btn = closeButton(modal);
    if (!btn) return;
    e.preventDefault();
    btn.click();
  });
})();

// Onyx and Black hats are hidden: if one of them is the selected tier, switch to gifts.
(() => {
  const fix = () => {
    const active = document.querySelector('.tier-btn.active[data-tier="onyx"], .tier-btn.active[data-tier="black"]');
    if (active) (document.querySelector('.tier-btn[data-tier="gift"]') || document.querySelector('.tier-btn[data-tier="random"]'))?.click();
  };
  setInterval(fix, 1500);
  document.addEventListener('DOMContentLoaded', fix);
})();

// Theme and day/night switches: at most one switch per second.
(() => {
  let last = 0;
  window.addEventListener('click', (e) => {
    if (!e.target.closest || !e.target.closest('#skyBtn, #tpApply')) return;
    const now = Date.now();
    if (now - last < 1000) { e.preventDefault(); e.stopImmediatePropagation(); return; }
    last = now;
  }, true);
})();

// Long gift names and prices: shrink the font until the text fits its box.
(() => {
  const SELECTOR = '.gp-name, .gp-price, .pname, .gift-name, .gift-price, .inv-name, .inv-price, .prize-name, .prize-price, '
    + '.cx-gift-name, .prize-value, .wd-btn, .stake-item b, .weapon-name, .upgrade-prize, .lb-prize-name, #cxWinGift, #bossLiveName, #statBestName, #lbPrizeName, #lbPrizeValue, #shopModalPrice, #stakingDepositName, #wpName, #tpName';
  const MIN = 0.72;
  function fit(el) {
    if (!el.isConnected || !el.clientWidth) return;
    el.classList.add('fit-text');
    el.style.fontSize = '';
    const base = parseFloat(getComputedStyle(el).fontSize) || 0;
    if (!base || el.scrollWidth <= el.clientWidth + 1) return;
    let size = base * Math.max(MIN, el.clientWidth / el.scrollWidth);
    el.style.fontSize = size.toFixed(2) + 'px';
    while (el.scrollWidth > el.clientWidth + 1 && size > base * MIN) {
      size -= 0.5; el.style.fontSize = size.toFixed(2) + 'px';
    }
  }
  let queued = false;
  const run = () => { queued = false; if (!window.__fitV2) document.querySelectorAll(SELECTOR).forEach(fit); };
  const schedule = () => { if (!queued) { queued = true; requestAnimationFrame(run); } };
  new MutationObserver((list) => {
    if (list.some((m) => m.type === 'childList' || m.type === 'characterData' || (m.attributeName === 'hidden'))) schedule();
  }).observe(document.documentElement, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['hidden'] });
  addEventListener('resize', schedule);
  document.addEventListener('DOMContentLoaded', schedule);
  // the pixel font arrives after the first layout: measure again once it is in
  try { document.fonts.ready.then(schedule); document.fonts.addEventListener('loadingdone', schedule); } catch (_) {}
  setInterval(schedule, 2000);
})();

// Season boss: animate HP loss (bar slides down, damage counts up, "-N HP" pops over the boss).
(() => {
  let shown = null;
  const fmtHp = (v) => (Math.round(v * 100) / 100).toLocaleString('ru-RU', { maximumFractionDigits: 2 });
  // Called by renderBossLeaderboard (index.html) after it has drawn the card.
  window.lbBossHpAnimate = (boss) => {
    {
      const result = undefined;
      const bar = document.getElementById('lbBossHealth'), text = document.getElementById('lbBossDamage');
      if (!boss || !bar || !text) { shown = null; return result; }
      const to = Math.min(boss.hp, boss.damage), key = boss.name + '|' + boss.hp;
      if (!shown || shown.key !== key || to <= shown.damage) { shown = { key, damage: to }; return result; }
      const from = shown.damage, label = text.textContent.split(':')[0];
      shown.damage = to;
      const start = performance.now(), dur = 900;
      const step = (t) => {
        const k = Math.min(1, (t - start) / dur), e = 1 - Math.pow(1 - k, 3), d = from + (to - from) * e;
        bar.value = Math.max(0, 1 - d / boss.hp);
        text.textContent = `${label}: ${fmtHp(d)} / ${fmtHp(boss.hp)} HP`;
        if (k < 1) requestAnimationFrame(step);
      };
      bar.value = Math.max(0, 1 - from / boss.hp);
      requestAnimationFrame(step);
      const card = document.getElementById('lbBoss'), art = document.getElementById('lbBossArt');
      if (card && !card.hidden) {
        const pop = document.createElement('div');
        pop.className = 'lb-boss-hit'; pop.textContent = `−${fmtHp(to - from)}`;
        const left = bar.offsetLeft + bar.offsetWidth * Math.max(0.08, Math.min(0.92, 1 - to / boss.hp));
        pop.style.left = left + 'px'; pop.style.top = (bar.offsetTop - 4) + 'px';
        card.appendChild(pop); setTimeout(() => pop.remove(), 1200);
        bar.classList.remove('hit'); void bar.offsetWidth; bar.classList.add('hit');
        if (art) { art.classList.remove('hit'); void art.offsetWidth; art.classList.add('hit'); }
      }
      return result;
    }
  };
})();

// Free spin window: an info button that explains how to earn coins with referrals.
(() => {
  const TEXT = [
    'Фри спин коины дают бесплатный прокрут Шляпы.',
    'Как получить: приглашай друзей по своей реферальной ссылке.',
    'Друг засчитывается, когда у него 2-й уровень в Telegram и пополнение от 1 GRAM.',
    'За каждых 10 засчитанных друзей — 1 фри спин коин.',
  ];
  const tr = (s) => (window.I18N && I18N.tr ? I18N.tr(s) : s);
  function add() {
    const card = document.querySelector('#freeCoinModal .coin-card');
    if (!card || card.querySelector('.coin-info-btn')) return;
    const btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'ghost coin-info-btn'; btn.textContent = 'i';
    btn.setAttribute('aria-label', tr('Как получить фри спин коины'));
    const box = document.createElement('div');
    box.className = 'coin-info-box'; box.hidden = true;
    for (const line of TEXT) { const p = document.createElement('p'); p.textContent = tr(line); box.appendChild(p); }
    btn.addEventListener('click', () => { box.hidden = !box.hidden; });
    card.prepend(btn);
    card.querySelector('h2')?.after(box);
  }
  new MutationObserver(add).observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener('DOMContentLoaded', add);
})();

// Gift names and prices v2: fit into the card, not just into their own box.
// Shrink the font first; a name that still does not fit is cut ("Intelligence C…", full name in the tooltip).
// Prices are never cut, only shrunk.
(() => {
  const CARDS = '.gp-head, .gp-item, .prize-card, .stake-item, .cx-win-card, .lb-prize-card, .weapon-card, .boss-prize, .shop-item, .upgrade-prize, #pbHud, #bossLiveHud';
  const TEXT = '#gpTitle, .gp-name, .gp-price, .pname, .prize-value, .wd-btn, .sell-btn, .stake-item b, .weapon-name, .upgrade-prize, #bossLiveName, .pb-title, '
    + '#cxWinGift, #lbPrizeName, #lbPrizeValue, #statBestName, #stakingDepositName, #shopModalPrice, .gift-name, .gift-price';
  const PRICE = '.gp-price, .prize-value, #lbPrizeValue, #shopModalPrice, .gift-price';
  function room(el) {
    const card = el.closest(CARDS) || el.parentElement;
    if (!card) return el.clientWidth;
    const cs = getComputedStyle(card);
    const inner = card.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const own = el.getBoundingClientRect(), box = card.getBoundingClientRect();
    const left = Math.max(0, own.left - box.left - parseFloat(cs.paddingLeft));
    const es = getComputedStyle(el);
    const pad = parseFloat(es.paddingLeft) + parseFloat(es.paddingRight) + parseFloat(es.borderLeftWidth) + parseFloat(es.borderRightWidth);
    return Math.max(10, Math.min(inner - left, el.parentElement ? el.parentElement.clientWidth : inner) - pad);
  }
  const textWidth = (el) => {
    const r = document.createRange(); r.selectNodeContents(el);
    return r.getBoundingClientRect().width;
  };
  function fit(el) {
    if (!el.isConnected || el.children.length) return;
    const shown = el.textContent;
    if (el.dataset.fitShown === shown && el.dataset.fitWidth === String(el.parentElement?.clientWidth)) return;
    const full = el.dataset.fitShown === shown && el.dataset.fitFull ? el.dataset.fitFull : shown;
    const price = el.matches(PRICE);
    el.dataset.fitFull = full;
    el.textContent = full; el.style.fontSize = ''; el.style.maxWidth = '';
    el.classList.add('fit-text');
    el.style.textOverflow = price ? 'clip' : '';
    const max = room(el);
    const base = parseFloat(getComputedStyle(el).fontSize) || 0;
    if (base && textWidth(el) > max + 0.5) {
      const min = base * (price ? 0.5 : 0.65);
      let size = Math.max(min, base * max / textWidth(el));
      el.style.fontSize = size.toFixed(2) + 'px';
      while (textWidth(el) > max + 0.5 && size > min) { size = Math.max(min, size - 0.25); el.style.fontSize = size.toFixed(2) + 'px'; }
      if (!price && textWidth(el) > max + 0.5) {
        let lo = 1, hi = full.length - 1;
        while (lo < hi) {
          const mid = (lo + hi + 1) >> 1;
          el.textContent = full.slice(0, mid).trimEnd() + '…';
          if (textWidth(el) <= max + 0.5) lo = mid; else hi = mid - 1;
        }
        el.textContent = full.slice(0, lo).trimEnd() + '…';
        el.title = full;
      }
    }
    el.dataset.fitShown = el.textContent;
    el.dataset.fitWidth = String(el.parentElement?.clientWidth);
  }
  let queued = false;
  const run = () => { queued = false; document.querySelectorAll(TEXT).forEach(fit); };
  const schedule = () => { if (!queued) { queued = true; requestAnimationFrame(run); } };
  new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['hidden'] });
  addEventListener('resize', schedule);
  document.addEventListener('DOMContentLoaded', schedule);
  try { document.fonts.ready.then(schedule); document.fonts.addEventListener('loadingdone', schedule); } catch (_) {}
  setInterval(schedule, 2000);
  window.__fitV2 = true;
})();

// Boss HUD on the main screen (Halloween): "−N HP" pops up from the end of the HP bar, the bar flashes.
window.bossLiveHit = (damage, hp, max) => {
  const hud = document.getElementById('bossLiveHud'), track = hud && hud.querySelector('.boss-live-track');
  if (!hud || hud.hidden || !track) return;
  const pop = document.createElement('div');
  pop.className = 'boss-live-pop';
  const n = Math.round(damage * 100) / 100;
  pop.textContent = '−' + n.toLocaleString('ru-RU', { maximumFractionDigits: 2 }) + ' HP';
  const x = track.offsetLeft + track.offsetWidth * Math.max(0.06, Math.min(0.94, max ? hp / max : 0));
  pop.style.left = x + 'px'; pop.style.top = track.offsetTop + 'px';
  hud.appendChild(pop);
  setTimeout(() => pop.remove(), 1300);
  track.classList.remove('hit'); void track.offsetWidth; track.classList.add('hit');
};

// Free spin info v2: the "i" button opens its own small window with one line.
(() => {
  function modal() {
    let m = document.getElementById('coinInfoModal');
    if (m) return m;
    m = document.createElement('div');
    m.className = 'modal'; m.id = 'coinInfoModal'; m.hidden = true; m.style.zIndex = '400';   // above the free spin window (180)
    m.innerHTML = '<section class="modal-card coin-card" role="dialog" aria-modal="true" aria-labelledby="coinInfoTitle">'
      + '<h2 id="coinInfoTitle">Фри спин коины</h2><p class="coin-info-line"></p>'
      + '<button class="cta" type="button" id="coinInfoClose">Понятно</button></section>';
    document.body.appendChild(m);
    const close = () => { m.hidden = true; };
    m.querySelector('#coinInfoClose').addEventListener('click', close);
    m.addEventListener('click', (e) => { if (e.target === m) close(); });
    return m;
  }
  document.addEventListener('click', (e) => {
    const btn = e.target.closest && e.target.closest('.coin-info-btn');
    if (!btn) return;
    e.preventDefault(); e.stopImmediatePropagation();
    document.querySelectorAll('.coin-info-box').forEach((b) => { b.hidden = true; });
    const m = modal();
    const tr = (s) => (window.I18N && I18N.tr ? I18N.tr(s) : s);
    m.querySelector('.coin-info-line').textContent = tr('Получайте фри спин коины за приглашения друзей');
    m.hidden = false;
  }, true);
})();

// Confirm window in the game style, titled "ШЛЯПА ДРОП" (the browser one shows the site address).
window.hdConfirm = (text) => new Promise((resolve) => {
  let m = document.getElementById('hdConfirm');
  if (!m) {
    m = document.createElement('div');
    m.className = 'modal'; m.id = 'hdConfirm'; m.hidden = true;
    m.innerHTML = '<section class="modal-card" role="alertdialog" aria-modal="true" aria-labelledby="hdConfirmTitle">'
      + '<h2 id="hdConfirmTitle">ШЛЯПА ДРОП</h2><p class="hd-confirm-text"></p>'
      + '<div class="hd-confirm-actions"><button class="ghost" type="button" data-answer="no">Отмена</button>'
      + '<button class="cta" type="button" data-answer="yes">OK</button></div></section>';
    document.body.appendChild(m);
  }
  const tr = (s) => (window.I18N && I18N.tr ? I18N.tr(s) : s);
  m.querySelector('.hd-confirm-text').textContent = text;
  m.querySelector('[data-answer=no]').textContent = tr('Отмена');
  const done = (yes) => { m.hidden = true; m.onclick = null; resolve(yes); };
  m.onclick = (e) => {
    const b = e.target.closest('[data-answer]');
    if (b) done(b.dataset.answer === 'yes'); else if (e.target === m) done(false);
  };
  m.hidden = false;
  m.querySelector('[data-answer=yes]').focus();
});
})()}catch(e){console.error("[app.js] ui-fixes.js",e)}
;

/* ===== inventory.js ===== */
try{
/* Инвентарь: подарки из профиля релеера (юзербот) + вывод 25 ★.
   API (ваш сервер):
     GET  /api/relayer/gifts -> { relayer:{username,name,updated_at}, stock:[{id,name,image,price,count}], mine:[{id,name,image,price}] }
     POST /api/inventory/claim {id}   — выдать подарок игроку
     POST /api/withdraw {stars:25}    — вывод статиков
   Если сервер не ответил — показываются демо-данные. */
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const px = (rects, c) => 'data:image/svg+xml,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" shape-rendering="crispEdges">${rects}</svg>`);
  const box = (a, b, r) => px(`<rect x="1" y="6" width="14" height="9" fill="#1a0f08"/><rect x="2" y="7" width="12" height="7" fill="${a}"/><rect x="1" y="4" width="14" height="3" fill="#1a0f08"/><rect x="2" y="5" width="12" height="1" fill="${b}"/><rect x="7" y="4" width="2" height="10" fill="${r}"/><rect x="4" y="2" width="4" height="2" fill="${r}"/><rect x="8" y="2" width="4" height="2" fill="${r}"/><rect x="7" y="3" width="2" height="1" fill="#1a0f08"/>`);
  const map = (rows, col, out = '#1a0f08') => px(rows.map((r, y) => [...r].map((ch, x) => ch === '#' ? `<rect x="${x + 2}" y="${y + 3}" width="1" height="1" fill="${col}"/>` : '').join('')).join(''));
  const heart = map(['.##..##.', '########', '########', '.######.', '..####..', '...##...'], '#ff5a7a');
  const cup = map(['########','#.####.#','#.####.#','.######.','..####..','...##...','..####..','.######.'], '#ffd24a');
  const star = map(['....#....', '...###...', '#########', '.#######.', '..#####..', '.###.###.', '.#.....#.'], '#ffd24a');
  const DEMO = {
    relayer: { username: 'relayer', name: 'Релеер', updated_at: Date.now() },
    stock: [
      { id: 'g1', name: 'Кубок', image: cup, price: 12.5, count: 3 },
      { id: 'g2', name: 'Топор', image: 'images/axe-icon.webp', price: 8, count: 2 },
      { id: 'g3', name: 'Посох', image: 'static/weapons/staff-v4-icon.svg', price: 20, count: 1 },
      { id: 'g4', name: 'Кристалл', image: 'images/gram-px.png', price: 5, count: 6 },
      { id: 'g5', name: 'Сердце', image: heart, price: 15, count: 4 },
      { id: 'g6', name: 'Звезда', image: star, price: 3, count: 10 },
      { id: 'g7', name: 'Красный бокс', image: box('#d6392f', '#ff7a5c', '#ffd24a'), price: 25, count: 2 },
      { id: 'g8', name: 'Синий бокс', image: box('#2f6fd6', '#6fb0ff', '#ffd24a'), price: 50, count: 1 },
      { id: 'g9', name: 'Зелёный бокс', image: box('#2fa05a', '#7be3a0', '#ffd24a'), price: 35, count: 1 }
    ],
    mine: [
      { id: 'm1', name: 'Кристалл', image: 'images/gram-px.png', price: 5 },
      { id: 'm2', name: 'Звезда', image: star, price: 3 },
      { id: 'm3', name: 'Красный бокс', image: box('#d6392f', '#ff7a5c', '#ffd24a'), price: 25 }
    ]
  };
  let data = null, tab = 'stock', demo = false;
  /* подарок StaticGram/Telegram: ссылка t.me/nft/slug-N, slug-N или /nft-img/slug-N.png -> PNG + живая анимация (telegram-gifts.js) */
  const slugOf = (it) => { const v = it.nft_slug || it.slug || it.link || it.url || it.image || ''; const m = String(v).match(/(?:nft-img\/|t\.me\/nft\/|^)([a-z][a-z0-9]{1,63}-[1-9][0-9]{0,10})(?:\.png|$)/i); return m ? m[1].toLowerCase() : null; };
  const setPic = (img, it) => { const s = slugOf(it); if (s) { img.dataset.nftSlug = s; img.src = '/nft-img/' + s + '.png'; } else { delete img.dataset.nftSlug; img.onerror = () => { img.onerror = null; img.src = '/images/gram-px.png'; }; img.src = it.image || '/images/gram-px.png'; } };
  /* api()/toast() из index.html внутри замыкания и отсюда не видны (раньше инвентарь всегда показывал демо) */
  const tgInit = () => (window.Telegram && Telegram.WebApp && Telegram.WebApp.initData) || new URLSearchParams(location.hash.slice(1)).get('tgWebAppData') || '';
  async function callApi(path, body) {
    let demoId = 'anon'; try { demoId = localStorage.getItem('demoId') || 'anon'; } catch (_) {}
    const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ initData: tgInit(), demoId, ...(body || {}) }) });
    let data = null; try { data = await res.json(); } catch (_) {}
    if (!res.ok) { const e = new Error((data && data.error) || ('HTTP ' + res.status)); e.data = data || {}; throw e; }
    return data;
  }
  const say = (text, err) => { const el = document.getElementById('toast'); if (!el) return; el.textContent = text; el.classList.toggle('err', !!err); el.hidden = false; clearTimeout(say.t); say.t = setTimeout(() => { el.hidden = true; }, err ? 4200 : 2600); };
  const fmt = (n) => (+n).toFixed(n % 1 ? 1 : 0);
  const balance = () => { const e = document.getElementById('balanceValue'); return e ? parseFloat(String(e.textContent).replace(',', '.')) || 0 : 0; };

  async function load() {
    try { const r = await callApi('/api/relayer/gifts'); if (r && r.stock) { data = r; demo = false; return; } } catch (_) {}
    /* внутри Telegram показываем пустой склад, а не выдуманные демо-подарки; демо только в обычном браузере */
    if (tgInit()) { data = { relayer: {}, stock: [], mine: [] }; demo = false; return; }
    data = DEMO; demo = true;
  }

  /* ---------- разметка ---------- */
  const view = document.createElement('section');
  view.className = 'view'; view.id = 'view-inventory'; view.hidden = true;
  view.innerHTML = `
    <button class="view-back" id="invBack" type="button" aria-label="Назад"><svg viewBox="0 0 16 16" shape-rendering="crispEdges"><path fill="currentColor" d="M9 2h3v2h-2v2H8V4h1zM6 6h2v2H6zM4 8h2v2H4zM6 10h2v2H6zM8 12h2v2H8zM10 12h2v2h-2z" opacity="0"/><path d="M10 2L4 8L10 14" fill="none" stroke="currentColor" stroke-width="3"/></svg></button>
    <h1 class="title">ИНВЕНТАРЬ</h1>
    <div class="inv-relayer"><div class="av">🎁</div><div class="tx"><b id="invRelName">@relayer</b><small id="invRelSub">подарки на складе</small></div><span class="live">LIVE</span></div>
    <div class="inv-tabs"><button class="inv-tab on" data-t="stock" type="button">СКЛАД <b id="invCntStock">0</b></button><button class="inv-tab" data-t="mine" type="button">МОИ <b id="invCntMine">0</b></button></div>
    <div class="inv-grid" id="invGrid"></div>
    <p class="inv-foot">Подарки лежат в профиле релеера.<br>Выиграл в апгрейде — подарок уходит тебе.</p>`;
  const modal = document.createElement('div');
  modal.className = 'modal'; modal.id = 'invModal'; modal.hidden = true;
  modal.innerHTML = `<div class="modal-card inv-modal"><h2 id="invMName">—</h2><div class="big"><img id="invMImg" alt=""></div>
    <div class="meta"><span id="invMPrice">—</span><span id="invMCnt">—</span></div>
    <button class="cta" id="invMAction" type="button"></button><button class="ghost" id="invMClose" type="button">Закрыть</button></div>`;

  function render() {
    if (!data) return;
    $('#invRelName', view).textContent = '@' + (data.relayer?.username || 'relayer');
    const total = data.stock.reduce((s, g) => s + (g.count || 1), 0);
    $('#invRelSub', view).textContent = `на складе ${total} шт · обновлено только что`;
    $('#invCntStock', view).textContent = total; $('#invCntMine', view).textContent = data.mine.length;
    const list = tab === 'stock' ? data.stock : data.mine, g = $('#invGrid', view); g.textContent = '';
    if (!list.length) { g.innerHTML = `<p class="inv-empty">${tab === 'mine' ? 'У тебя пока нет подарков.<br>Выиграй первый в апгрейде!' : 'Склад пуст'}</p>`; return; }
    for (const it of list) {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'inv-card' + (tab === 'mine' ? ' mine' : '');
      b.innerHTML = `${it.count > 1 ? `<span class="cnt">x${it.count}</span>` : ''}<span class="im"><img alt="" loading="lazy"></span><span class="nm"></span><span class="pr"></span>`;
      setPic($('img', b), it); $('.nm', b).textContent = it.name; $('.pr', b).textContent = fmt(it.price) + ' ★';
      b.onclick = () => openItem(it); g.appendChild(b);
    }
  }
  function openItem(it) {
    $('#invMName').textContent = it.name; setPic($('#invMImg'), it);
    $('#invMPrice').textContent = fmt(it.price) + ' ★'; $('#invMCnt').textContent = tab === 'stock' ? `на складе: ${it.count || 1}` : 'в твоём профиле';
    const a = $('#invMAction'); a.textContent = tab === 'stock' ? 'ВЫБРАТЬ В АПГРЕЙД' : 'ЗАБРАТЬ В ПРОФИЛЬ';
    a.onclick = async () => { modal.hidden = true; if (tab === 'stock') { $('#tabMenu') && document.querySelector('.tab[data-view="upgrade"]').click(); } else { try { const r = await callApi('/api/inventory/claim', { id: it.id }); say((r && r.message) || 'Подарок в очереди на отправку'); load().then(render); } catch (e) { say((e && e.data && e.data.message) || (e && e.message) || 'Не удалось забрать подарок', true); } } };
    modal.hidden = false;
  }

  /* ---------- навигация (в обход whitelist showView) ---------- */
  function open() {
    document.querySelectorAll('.view').forEach((v) => { if (v !== view) v.hidden = true; });
    view.hidden = false; document.body.dataset.view = 'inventory';
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.view === 'menu'));
    const c = document.querySelector('.content'); if (c) c.scrollTop = 0;
    load().then(render);
  }
  function hideOnOtherView() { if (!view.hidden && [...document.querySelectorAll('.view')].some((v) => v !== view && !v.hidden)) view.hidden = true; }

  /* ---------- GRAM -> ★ в видимом тексте ---------- */
  function toStar(root) {
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n; (n = w.nextNode());) if (/\bGRAM\b/.test(n.nodeValue) && !n.parentElement.closest('script,style')) n.nodeValue = n.nodeValue.replace(/\bGRAM\b/g, '★');
  }

  function init() {
    const content = $('#view-profile')?.parentElement; if (!content) return setTimeout(init, 200);
    content.appendChild(view); document.body.appendChild(modal);
    $('#invBack').onclick = () => $('#tabMenu').click();
    $('#invMClose').onclick = () => { modal.hidden = true; };
    view.querySelectorAll('.inv-tab').forEach((b) => b.onclick = () => { tab = b.dataset.t; view.querySelectorAll('.inv-tab').forEach((x) => x.classList.toggle('on', x === b)); render(); });
    /* 4-я карточка в меню */
    const grid = $('#view-menu .menu-grid');
    if (grid && !$('#menuInventory')) {
      const c = document.createElement('button'); c.className = 'menu-card menu-wide'; c.id = 'menuInventory'; c.type = 'button';
      c.innerHTML = `<span class="mc-medal"><svg class="mc-art mc-svg" viewBox="0 0 16 16" aria-hidden="true" shape-rendering="crispEdges"><path fill="#f0892a" stroke="#250f05" stroke-width="1" paint-order="stroke" d="M1.5 5.5H14.5V14.5H1.5ZM1.5 3.5H14.5V5.5H1.5ZM7 3.5V14.5H9V3.5ZM4.5 1.5H7.5V3.5H4.5ZM8.5 1.5H11.5V3.5H8.5Z" fill-rule="evenodd"/></svg></span><span class="mc-text"><b class="mc-title">ИНВЕНТАРЬ</b><small class="mc-sub">Подарки релеера</small></span>`;
      c.onclick = open; grid.appendChild(c);
    }
    const mo = new MutationObserver(() => { hideOnOtherView(); });
    document.querySelectorAll('.view').forEach((v) => { if (v !== view) mo.observe(v, { attributes: true, attributeFilter: ['hidden'] }); });
    new MutationObserver((m) => m.forEach((r) => r.addedNodes.forEach((n) => n.nodeType === 1 && toStar(n)))).observe(document.body, { childList: true, subtree: true });
    new MutationObserver((m) => m.forEach((r) => r.type === 'characterData' && toStar(r.target.parentNode || document.body))).observe(document.body, { characterData: true, subtree: true });
    toStar(document.body); load().then(render);
    setInterval(() => { toStar(document.body); }, 1500);
    window.RelayerInventory = { demo: DEMO, open, reload: () => load().then(render) };
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
}catch(e){console.error("[app.js] inventory.js",e)}
;

/* ===== economy.js ===== */
try{
/* Экономика WinLine:
   • монетки (1 монета = 1 ★) — слева в шапке, это основной баланс;
   • алмазы 💎 — справа в шапке, награда, обмен на монетки в «Наградах»;
   • вывод ЗВЁЗД из профиля: ровно 25 ★ за раз.
   API (ваш сервер):
     GET  /api/rewards          -> { gems, tasks:[{id,title,desc,reward,progress,goal,claimed}], exchange:[{gems,coins}] }
     POST /api/rewards/claim    {id}
     POST /api/rewards/exchange {gems}
     POST /api/withdraw         {stars:25}
   Нет ответа сервера — демо-данные. */
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const fmt = (n) => (+n % 1 ? (+n).toFixed(2) : String(+n));
  const WITHDRAW_STEP = 25;
  const GEM = 'images/gram-px.png', COIN = 'images/hatcoin.png';
  const DEMO = {
    gems: 12,
    tasks: [
      { id: 'daily', title: 'Ежедневный вход', desc: 'Заходи каждый день. 7 дней подряд — бонус', reward: 1, progress: 1, goal: 1, claimed: false },
      { id: 'streak3', title: 'Серия апгрейдов', desc: 'Выиграй 3 апгрейда подряд', reward: 1, progress: 2, goal: 3, claimed: false },
      { id: 'mines10', title: 'Кладбище', desc: 'Открой 10 гробов в «Минах»', reward: 1, progress: 10, goal: 10, claimed: false },
      { id: 'turn500', title: 'Оборот 500 монет', desc: 'Крути апгрейд и мины', reward: 2, progress: 140, goal: 500, claimed: false },
      { id: 'friend', title: 'Позови друга', desc: 'Друг зашёл по твоей ссылке', reward: 3, progress: 0, goal: 1, claimed: false }
    ],
    exchange: [{ gems: 10, coins: 200 }, { gems: 25, coins: 550 }, { gems: 50, coins: 1200 }, { gems: 100, coins: 2600 }]
  };
  let data = null, demo = false;
  const coins = () => { const e = document.getElementById('balanceValue'); return e ? parseFloat(String(e.textContent).replace(',', '.')) || 0 : 0; };

  async function load() {
    try { const r = await (typeof api === 'function' ? api('/api/rewards') : Promise.reject()); if (r && r.tasks) { data = r; demo = false; return; } } catch (_) {}
    if (!data) data = JSON.parse(JSON.stringify(DEMO));
    demo = true;
  }
  const call = async (path, body) => { if (demo) return null; try { return await api(path, body); } catch (_) { return null; } };

  /* ---------- шапка: монетки слева, алмазы справа ---------- */
  function header() {
    const cc = $('#coinChip'), bc = $('#balanceChip');
    if (!cc || !bc) return;
    if (!$('#coinMine')) {
      const a = document.createElement('span'); a.id = 'coinMine'; $('#coinValue').after(a);
      const g = document.createElement('span'); g.id = 'gemMine'; $('#balanceValue').after(g);
      cc.title = 'Монетки: 1 монета = 1 ★'; bc.title = 'Алмазы — награды';
      document.documentElement.setAttribute('data-econ', '1');
    }
    $('#coinMine').textContent = coins().toFixed(2);
    if (data) $('#gemMine').textContent = String(data.gems);
  }
  document.addEventListener('click', (e) => {
    const t = e.target.closest && e.target.closest('#coinChip,#balanceChip'); if (!t) return;
    e.preventDefault(); e.stopImmediatePropagation();
    if (t.id === 'balanceChip') openRewards(); else { const p = document.querySelector('.tab[data-view="profile"]'); p && p.click(); }
  }, true);

  /* ---------- экран «Награды» ---------- */
  const view = document.createElement('section');
  view.className = 'view'; view.id = 'view-rewards'; view.hidden = true;
  view.innerHTML = `
    <button class="view-back" id="rwBack" type="button" aria-label="Назад"><svg viewBox="0 0 16 16" shape-rendering="crispEdges"><path d="M10 2L4 8L10 14" fill="none" stroke="currentColor" stroke-width="3"/></svg></button>
    <h1 class="title">НАГРАДЫ</h1>
    <div class="rw-gems"><img src="${GEM}" alt=""><div><small>ТВОИ АЛМАЗЫ</small><b id="rwGems">0</b></div></div>
    <h2 class="rw-h">ОБМЕН АЛМАЗОВ</h2>
    <div class="rw-ex" id="rwEx"></div>
    <h2 class="rw-h">КАК ПОЛУЧИТЬ АЛМАЗЫ</h2>
    <div class="rw-tasks" id="rwTasks"></div>
    <p class="inv-foot">1 монета = 1 ★. Монетки можно вывести звёздами от 25 ★ за раз.</p>`;

  function renderRewards() {
    if (!data) return;
    $('#rwGems', view).textContent = data.gems;
    const ex = $('#rwEx', view); ex.textContent = '';
    for (const t of data.exchange) {
      const ok = data.gems >= t.gems, row = document.createElement('div'); row.className = 'rw-row';
      row.innerHTML = `<span class="l"><img src="${GEM}" alt=""><b>${t.gems}</b></span><span class="ar">→</span><span class="r"><img src="${COIN}" alt=""><b>${t.coins}</b></span><button type="button" class="rw-btn" ${ok ? '' : 'disabled'}>ОБМЕН</button>`;
      $('button', row).onclick = async () => {
        if (!ok) return;
        if (demo) { data.gems -= t.gems; const e = document.getElementById('balanceValue'); if (e) e.textContent = String(coins() + t.coins); }
        else { await call('/api/rewards/exchange', { gems: t.gems }); await load(); }
        header(); renderRewards();
      };
      ex.appendChild(row);
    }
    const tl = $('#rwTasks', view); tl.textContent = '';
    for (const k of data.tasks) {
      const done = k.progress >= k.goal, pct = Math.min(100, k.progress / k.goal * 100), card = document.createElement('div');
      card.className = 'rw-task' + (k.claimed ? ' claimed' : done ? ' ready' : '');
      card.innerHTML = `<div class="top"><b>${k.title}</b><span class="rw-chip">+${k.reward} <img src="${GEM}" alt=""></span></div><small>${k.desc}</small><div class="rw-bar"><i style="width:${pct}%"></i></div><div class="bot"><span>${Math.min(k.progress, k.goal)}/${k.goal}</span><button type="button" class="rw-btn" ${done && !k.claimed ? '' : 'disabled'}>${k.claimed ? 'ПОЛУЧЕНО' : 'ЗАБРАТЬ'}</button></div>`;
      $('button', card).onclick = async () => {
        if (!done || k.claimed) return;
        if (demo) { k.claimed = true; data.gems += k.reward; } else { await call('/api/rewards/claim', { id: k.id }); await load(); }
        header(); renderRewards();
      };
      tl.appendChild(card);
    }
  }
  function openRewards() {
    document.querySelectorAll('.view').forEach((v) => { if (v !== view) v.hidden = true; });
    view.hidden = false; document.body.dataset.view = 'rewards';
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.view === 'menu'));
    const c = document.querySelector('.content'); if (c) c.scrollTop = 0;
    load().then(() => { header(); renderRewards(); });
  }
  const hideOnOtherView = () => { if (!view.hidden && [...document.querySelectorAll('.view')].some((v) => v !== view && !v.hidden)) view.hidden = true; };

  /* ---------- вывод ЗВЁЗД в профиле ---------- */
  function wdCard() {
    const anchor = $('#view-profile .pstats'); if (!anchor) return;
    const bal = coins(), ok = bal >= WITHDRAW_STEP, key = bal + '|' + ok;
    const old = $('#wdCard'); if (old && old.dataset.k === key) return; if (old) old.remove();
    const left = Math.max(0, WITHDRAW_STEP - bal), card = document.createElement('div');
    card.className = 'wd-card'; card.id = 'wdCard'; card.dataset.k = key;
    card.innerHTML = `<h3>ВЫВОД ЗВЁЗД</h3>
      <div class="wd-bal"><img src="${COIN}" alt=""><b>${fmt(bal)}</b><span>монет</span><em>1 монета = 1 ★</em></div>
      <div class="wd-bar"><i style="width:${Math.min(100, bal / WITHDRAW_STEP * 100)}%"></i></div>
      <p>${ok ? `Можно вывести ровно ${WITHDRAW_STEP} ★ за раз. Спишется ${WITHDRAW_STEP} монет.` : `Нужно ещё ${fmt(left)} монет до вывода. Вывод — ровно ${WITHDRAW_STEP} ★ за раз.`}</p>
      <button class="wd-btn" type="button" ${ok ? '' : 'disabled'}>ВЫВЕСТИ ${WITHDRAW_STEP} ★</button>
      <div class="wd-mini"><button type="button" id="wdInv">🎁 ИНВЕНТАРЬ</button><button type="button" id="wdRw">💎 НАГРАДЫ</button></div>`;
    $('.wd-btn', card).onclick = async () => { try { await api('/api/withdraw', { stars: WITHDRAW_STEP }); } catch (_) {} };
    $('#wdInv', card).onclick = () => window.RelayerInventory && window.RelayerInventory.open();
    $('#wdRw', card).onclick = openRewards;
    anchor.after(card);
  }

  function init() {
    const content = $('#view-profile')?.parentElement; if (!content || !$('#coinChip')) return setTimeout(init, 200);
    content.appendChild(view);
    $('#rwBack').onclick = () => $('#tabMenu').click();
    const grid = $('#view-menu .menu-grid');
    if (grid && !$('#menuRewards')) {
      const c = document.createElement('button'); c.className = 'menu-card menu-wide'; c.id = 'menuRewards'; c.type = 'button';
      c.innerHTML = `<span class="mc-medal"><svg class="mc-art mc-svg" viewBox="0 0 16 16" aria-hidden="true" shape-rendering="crispEdges"><path fill="#f0892a" stroke="#250f05" stroke-width="1" paint-order="stroke" d="M4.5 1.5H11.5L14.5 5.5L8 14.5L1.5 5.5ZM4.5 5.5L8 11.5L11.5 5.5Z" fill-rule="evenodd"/></svg></span><span class="mc-text"><b class="mc-title">НАГРАДЫ</b><small class="mc-sub">Алмазы и обмен</small></span>`;
      c.onclick = openRewards; grid.appendChild(c);
    }
    const mo = new MutationObserver(hideOnOtherView);
    document.querySelectorAll('.view').forEach((v) => { if (v !== view) mo.observe(v, { attributes: true, attributeFilter: ['hidden'] }); });
    header(); wdCard(); load().then(() => { header(); renderRewards(); });
    setInterval(() => { header(); wdCard(); }, 700);
    window.Economy = { openRewards, reload: () => load().then(() => { header(); renderRewards(); }), demo: DEMO };
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
}catch(e){console.error("[app.js] economy.js",e)}
;

/* ===== maintenance-gate.js ===== */
try{
/* Техперерыв: полноэкранная картинка /static/maintenance-screen.png.
   Показывается только если сервер сказал blocked=true (владелец и админы проходят). */
(async function () {
  try {
    const init = (window.Telegram && Telegram.WebApp && Telegram.WebApp.initData) || "";
    const r = await fetch("/api/maintenance", { cache: "no-store", headers: { "X-Init-Data": init } });
    const j = await r.json();
    if (!j.maintenance || !j.blocked) return;
    const ov = document.createElement("div");
    ov.id = "maintOverlay";
    ov.style.cssText = "position:fixed;inset:0;z-index:99999;background:#0a0a12 center/cover no-repeat;background-image:url('/static/maintenance-screen.png');";
    document.body.appendChild(ov);
  } catch (_) {}
})();
}catch(e){console.error("[app.js] maintenance-gate.js",e)}
;
