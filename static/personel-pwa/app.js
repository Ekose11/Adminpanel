const API='';
let token=localStorage.getItem('personel_token')||'';
let person={};
let scanner=null;
let scannerRunning=false;
let scanLocked=false;
let selectedAction='entry';
let lastRequestAt=0;
let lastNotificationId=Number(localStorage.getItem('personel_last_notification_id')||0);
let notificationPollStarted=false;

const $=id=>document.getElementById(id);
const money=v=>new Intl.NumberFormat('tr-TR',{maximumFractionDigits:2}).format(Number(v||0))+' TL';
const formBody=data=>new URLSearchParams(data).toString();
function b64ToUint(s){const pad='='.repeat((4-s.length%4)%4),raw=atob((s+pad).replace(/-/g,'+').replace(/_/g,'/'));return Uint8Array.from([...raw].map(c=>c.charCodeAt(0)))}
async function enablePersonPush(){
  const st=$('pushStatus');
  if(!token||!('serviceWorker'in navigator)||!('PushManager'in window)||!('Notification'in window)){if(st)st.textContent='Bu cihaz kapalı bildirimleri desteklemiyor.';return;}
  if(st)st.textContent='Bildirim kuruluyor…';
  try{
    const reg=await navigator.serviceWorker.register('/personel/service-worker.js',{scope:'/personel/'});
    if(Notification.permission==='default')await Notification.requestPermission();
    if(Notification.permission!=='granted')return;
    const key=await request('/api/push/public-key');
    let sub=await reg.pushManager.getSubscription();
    if(!sub)sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:b64ToUint(key.public_key)});
    await request('/api/push/subscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({audience:'personel',token,subscription:sub.toJSON()})});
    if(st)st.textContent='✓ Uygulama kapalıyken ve ekran kilitliyken bildirim açık.';
  }catch(e){if(st)st.textContent='Bildirim açılamadı: '+e.message;console.warn('Kapalı bildirim etkinleştirilemedi',e)}
}


async function updatePushState(){
  const st=$('pushStatus'),btn=$('enablePushBtn');
  if(!st||!btn)return;
  if(!('Notification'in window)){st.textContent='Bu tarayıcı bildirim desteklemiyor.';btn.disabled=true;return;}
  if(Notification.permission==='denied'){st.textContent='Bildirim izni telefon ayarlarından kapalı.';return;}
  try{const reg=await navigator.serviceWorker.ready;const sub=await reg.pushManager.getSubscription();if(sub&&Notification.permission==='granted'){st.textContent='✓ Telefon bildirimleri açık.';btn.textContent='🔔 Bildirimler açık';}}catch(e){}
}

function toast(msg){const t=$('toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2600)}
async function request(path,opts={}){const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),12000);let r;try{r=await fetch(API+path,{cache:'no-store',signal:controller.signal,...opts})}finally{clearTimeout(timer)};const text=await r.text();let data;try{data=JSON.parse(text)}catch{throw new Error('Sunucu geçersiz cevap verdi')}if(!r.ok)throw new Error(data.message||'Sunucu hatası');return data}
function showLogin(){stopScanner();$('loginView').classList.remove('hidden');$('appView').classList.add('hidden')}
function showApp(){ $('loginView').classList.add('hidden');$('appView').classList.remove('hidden');showPage('homePage');startNotificationPolling();updatePushState() }
function showPage(id){document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));$(id).classList.add('active');document.querySelectorAll('.bottom-nav button').forEach(x=>x.classList.toggle('active',x.dataset.page===id));if(id!=='scannerPage')stopScanner();if(id==='notificationsPage')loadNotifications();if(id==='advancesPage'){loadAdvanceRequests();loadAdvances();}if(id==='profilePage')fillProfile();if(id==='bonusPage')loadBonuses()}
function setConnected(ok){const el=$('serverState');el.textContent=ok?'● Bağlı':'● Bağlantı Yok';el.className='pill '+(ok?'online':'offline')}
function fillPerson(p){if(!p)return;person=p;$('fullName').textContent=p.full_name||'-';$('welcomeName').textContent='Hoş geldin, '+(p.full_name||'Personel').split(' ')[0];$('department').textContent=p.department||'-';$('leaveValue').textContent=(p.annual_leave_remaining||0)+' gün';$('remainingSalary').textContent=money(p.remaining_salary);$('totalAdvance').textContent=money(p.total_advance);$('profilePhone').value=p.phone||'';$('profileAddress').value=p.address||'';$('monthlyBonus').textContent=money(p.monthly_bonus||0);if(p.photo_data)$('avatar').src=p.photo_data}
async function login(){const u=$('username').value.trim(),p=$('password').value;if(!u||!p){$('loginStatus').textContent='Kullanıcı adı ve şifre girin.';return}const b=$('loginBtn');b.disabled=true;$('loginStatus').textContent='Giriş yapılıyor…';try{const d=await request('/api/employee-login?username='+encodeURIComponent(u)+'&password='+encodeURIComponent(p));if(d.status!=='ok')throw new Error(d.message||'Giriş başarısız');token=d.token;localStorage.setItem('personel_token',token);fillPerson(d.person);showApp();setConnected(true);refresh()}catch(e){$('loginStatus').textContent=e.message;setConnected(false)}finally{b.disabled=false}}
async function refresh(){try{const me=await request('/api/employee-me?token='+encodeURIComponent(token));if(me.status!=='ok')throw new Error(me.message||'Oturum kapandı');fillPerson(me.person);setConnected(true)}catch(e){setConnected(false);if(/oturum|token|giriş/i.test(e.message)){localStorage.removeItem('personel_token');token='';showLogin()}else toast(e.message)}}
function openScanner(action){selectedAction=action;$('scannerTitle').textContent=action==='entry'?'QR Giriş':'QR Çıkış';$('scannerStatus').textContent='Kamera hazırlanıyor…';showPage('scannerPage');startScanner()}
async function startScanner(){if(scannerRunning||scanLocked)return;if(typeof Html5Qrcode==='undefined'){$('scannerStatus').textContent='QR motoru yüklenemedi.';return}scanner=new Html5Qrcode('reader',{verbose:false});scanLocked=false;try{const cams=await Html5Qrcode.getCameras();const rear=cams.find(c=>/back|rear|environment|arka/i.test(c.label))||cams[cams.length-1];if(!rear)throw new Error('Kamera bulunamadı');scannerRunning=true;await scanner.start(rear.id,{fps:24,qrbox:(w,h)=>({width:Math.min(w,h)*.72,height:Math.min(w,h)*.72}),aspectRatio:1.0,disableFlip:true},onScan,()=>{});$('scannerStatus').textContent='QR kodu okutun.'}catch(e){scannerRunning=false;$('scannerStatus').textContent='Kamera açılamadı: '+e.message}}
async function stopScanner(){if(scanner&&scannerRunning){try{await scanner.stop();await scanner.clear()}catch{} }scanner=null;scannerRunning=false}
async function onScan(decoded){const now=Date.now();if(scanLocked||now-lastRequestAt<8000)return;scanLocked=true;lastRequestAt=now;$('scannerStatus').textContent='QR okundu. Kamera kapatılıyor…';if(navigator.vibrate)navigator.vibrate(120);await stopScanner();try{const requestId=(crypto.randomUUID?crypto.randomUUID():Date.now()+'-'+Math.random());const d=await request('/api/qr/verify',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8'},body:formBody({person_token:token,qr:decoded,action:selectedAction,request_id:requestId})});if(d.status!=='ok')throw new Error(d.message||'QR doğrulanamadı');$('scannerStatus').textContent=(selectedAction==='entry'?'Giriş':'Çıkış')+' kaydedildi • '+(d.full_name||'');toast('İşlem başarıyla kaydedildi');setTimeout(()=>{scanLocked=false;showPage('homePage');refresh()},1300)}catch(e){$('scannerStatus').textContent=e.message;toast(e.message);setTimeout(()=>{scanLocked=false},2500)}}
async function sendLeave(){const s=$('leaveStart').value,e=$('leaveEnd').value,type=$('leaveType').value,n=$('leaveNote').value.trim();if(!s||!e){$('leaveStatus').textContent='Başlangıç ve bitiş tarihini seçin.';return}if(e<s){$('leaveStatus').textContent='Bitiş tarihi başlangıçtan önce olamaz.';return}const b=$('sendLeaveBtn');if(b.disabled)return;b.disabled=true;$('leaveStatus').textContent='Talep gönderiliyor…';try{const d=await request('/api/employee-leave-request',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8'},body:formBody({token,start_date:s,end_date:e,note:type+(n?' - '+n:'')})});$('leaveStatus').textContent=d.message||'Talep gönderildi.';toast('İzin talebi gönderildi');$('leaveNote').value=''}catch(err){$('leaveStatus').textContent=err.message}finally{b.disabled=false}}
async function loadNotifications(){const box=$('notificationsList');box.innerHTML='<div class="empty">Bildirimler yükleniyor…</div>';try{const d=await request('/api/employee-notifications?token='+encodeURIComponent(token));const a=d.notifications||[];box.innerHTML=a.length?a.map(x=>`<article class="list-card ${Number(x.is_read||0)===0?'unread':''}"><h3>${escapeHtml(x.event_type||'Bildirim')}</h3><p>${escapeHtml(x.message||'')}</p><small>${escapeHtml(x.created_at||'')}</small></article>`).join(''):'<div class="empty">Henüz bildirim yok.</div>';await request('/api/employee-notifications/read',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8'},body:formBody({token})});updateNotificationBadge(0)}catch(e){box.innerHTML='<div class="empty">'+escapeHtml(e.message)+'</div>'}}

function statusClass(v){v=String(v||'').toLowerCase();return v.includes('onay')?'status-ok':v.includes('red')?'status-no':'status-wait'}
async function sendAdvance(){const amount=$('advanceAmount').value,note=$('advanceNote').value.trim();if(!amount||Number(amount)<=0){$('advanceStatus').textContent='Geçerli bir tutar girin.';return}const b=$('sendAdvanceBtn');b.disabled=true;$('advanceStatus').textContent='Talep gönderiliyor…';try{const d=await request('/api/employee-advance-request',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8'},body:formBody({token,amount,note})});$('advanceStatus').textContent=d.message||'Talep gönderildi.';$('advanceAmount').value='';$('advanceNote').value='';toast('Avans talebi gönderildi');loadAdvanceRequests()}catch(e){$('advanceStatus').textContent=e.message}finally{b.disabled=false}}
async function loadAdvanceRequests(){const box=$('advanceRequestsList');if(!box)return;box.innerHTML='<div class="empty">Talepler yükleniyor…</div>';try{const d=await request('/api/employee-advance-requests?token='+encodeURIComponent(token));const a=d.requests||[];box.innerHTML=a.length?a.map(x=>`<article class="list-card"><h3>${money(x.amount)}</h3><p class="${statusClass(x.status)}">${escapeHtml(x.status||'Beklemede')}</p><p>${escapeHtml(x.note||'-')}</p><small>${escapeHtml(x.created_at||'')}</small></article>`).join(''):'<div class="empty">Henüz avans talebi yok.</div>'}catch(e){box.innerHTML='<div class="empty">'+escapeHtml(e.message)+'</div>'}}
function updateNotificationBadge(n){const el=$('personNotificationBadge');if(!el)return;el.textContent=n;el.classList.toggle('hidden',!n)}
function notificationSound(){try{const C=window.AudioContext||window.webkitAudioContext;if(!C)return;const c=new C(),o=c.createOscillator(),g=c.createGain();o.connect(g);g.connect(c.destination);o.frequency.value=880;g.gain.setValueAtTime(.12,c.currentTime);g.gain.exponentialRampToValueAtTime(.001,c.currentTime+.35);o.start();o.stop(c.currentTime+.35)}catch(e){}if(navigator.vibrate)navigator.vibrate([120,80,120])}
async function pollNotifications(){
  if(!token||document.hidden)return;
  try{
    const d=await request('/api/employee-notifications/pending?token='+encodeURIComponent(token));
    const items=d.notifications||[];
    if(items.length){
      const latest=items[items.length-1];
      notificationSound();
      toast(latest.event_type+': '+latest.message);
      if('Notification'in window&&Notification.permission==='granted'){
        new Notification(latest.event_type,{body:latest.message,icon:'/static/personel-pwa/icons/icon-192.png',tag:'boztek-'+latest.id});
      }
      loadNotificationBadge();
    }
  }catch(e){}
}
async function loadNotificationBadge(){
  if(!token)return;
  try{const d=await request('/api/employee-notifications?token='+encodeURIComponent(token));updateNotificationBadge((d.notifications||[]).filter(x=>Number(x.is_read||0)===0).length)}catch(e){}
}
function startNotificationPolling(){
  if(notificationPollStarted)return;notificationPollStarted=true;
  if('Notification'in window&&Notification.permission==='default'){document.addEventListener('click',()=>Notification.requestPermission(),{once:true})}
  loadNotificationBadge();
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)loadNotificationBadge()});
}

async function loadBonuses(){
  const month=$('bonusMonth').value||new Date().toISOString().slice(0,7);
  const box=$('bonusList');box.innerHTML='<div class="empty">Primler yükleniyor…</div>';
  try{const d=await request('/api/employee-bonuses?token='+encodeURIComponent(token)+'&month='+encodeURIComponent(month));$('bonusTotal').textContent=money(d.total);box.innerHTML=(d.bonuses||[]).length?d.bonuses.map(x=>`<article class="list-card"><h3>${money(x.amount)}</h3><p>${escapeHtml(x.note||'-')}</p><small>${escapeHtml(x.bonus_date||'')}</small></article>`).join(''):'<div class="empty">Bu ay prim kaydı yok.</div>'}catch(e){box.innerHTML='<div class="empty">'+escapeHtml(e.message)+'</div>'}
}


async function loadAdvances(){const box=$('advancesList');box.innerHTML='<div class="empty">Avanslar yükleniyor…</div>';try{const d=await request('/api/employee-advances?token='+encodeURIComponent(token));const a=d.advances||[];box.innerHTML=a.length?a.map(x=>`<article class="list-card"><h3>${money(x.amount)}</h3><p>${escapeHtml(x.status||'')}</p><small>${escapeHtml(x.created_at||x.date||'')}</small></article>`).join(''):'<div class="empty">Avans kaydı bulunamadı.</div>'}catch(e){box.innerHTML='<div class="empty">'+escapeHtml(e.message)+'</div>'}}
function fillProfile(){$('profilePhone').value=person.phone||'';$('profileAddress').value=person.address||''}
async function imageData(file){if(!file)return person.photo_data||'';return new Promise((res,rej)=>{const img=new Image(),r=new FileReader();r.onload=()=>img.src=r.result;img.onload=()=>{const max=520,scale=Math.min(1,max/Math.max(img.width,img.height)),c=document.createElement('canvas');c.width=Math.round(img.width*scale);c.height=Math.round(img.height*scale);c.getContext('2d').drawImage(img,0,0,c.width,c.height);res(c.toDataURL('image/jpeg',.72))};r.onerror=rej;r.readAsDataURL(file)})}
async function saveProfile(){const b=$('saveProfileBtn');b.disabled=true;$('profileStatus').textContent='Profil kaydediliyor…';try{const photo=await imageData($('profilePhoto').files[0]);const d=await request('/api/employee-profile',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8'},body:formBody({token,phone:$('profilePhone').value.trim(),address:$('profileAddress').value.trim(),photo_data:photo})});if(d.status!=='ok')throw new Error(d.message||'Kayıt başarısız');fillPerson(d.person);$('profileStatus').textContent=d.message||'Profil kaydedildi.';toast('Profil güncellendi')}catch(e){$('profileStatus').textContent=e.message}finally{b.disabled=false}}
function logout(){localStorage.removeItem('personel_token');token='';person={};showLogin()}
function escapeHtml(v){return String(v).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}

document.addEventListener('click',e=>{const p=e.target.closest('[data-page]');if(p)showPage(p.dataset.page);const s=e.target.closest('[data-open-scanner]');if(s)openScanner(s.dataset.openScanner)});
$('loginBtn').onclick=login;$('enablePushBtn').onclick=enablePersonPush;$('password').addEventListener('keydown',e=>{if(e.key==='Enter')login()});$('refreshBtn').onclick=refresh;$('startScannerBtn').onclick=startScanner;$('stopScannerBtn').onclick=stopScanner;$('sendLeaveBtn').onclick=sendLeave;$('sendAdvanceBtn').onclick=sendAdvance;$('saveProfileBtn').onclick=saveProfile;$('logoutBtn').onclick=logout;
const today=new Date().toISOString().slice(0,10);$('leaveStart').value=today;$('leaveEnd').value=today;$('bonusMonth').value=today.slice(0,7);$('bonusMonth').addEventListener('change',loadBonuses);

if(token){showApp();refresh()}else showLogin();