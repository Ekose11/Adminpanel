self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('push', event => {
  let data={title:'Personel Sistemi',body:'Yeni bildirim',url:'/admin/dashboard',tag:'admin-push'};
  try{data={...data,...event.data.json()}}catch(e){try{data.body=event.data.text()}catch(_){}}
  event.waitUntil(self.registration.showNotification(data.title,{body:data.body,icon:'/static/pwa/icon-192.png',badge:'/static/pwa/icon-192.png',tag:data.tag||'admin-push',renotify:false,vibrate:[180,80,180],data:{url:data.url||'/admin/dashboard'}}));
});
self.addEventListener('notificationclick',event=>{event.notification.close();const url=event.notification.data?.url||'/admin/dashboard';event.waitUntil(clients.matchAll({type:'window',includeUncontrolled:true}).then(list=>{for(const c of list){if('focus'in c){c.navigate(url);return c.focus()}}return clients.openWindow(url)}))});