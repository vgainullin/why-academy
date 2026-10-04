// The GitHub Pages copy has no API, so accounts and sync cannot work there.
// Send visitors to the Cloudflare deployment, keeping the path and query.
(function () {
  if (location.hostname !== 'vgainullin.github.io') return;
  const path = location.pathname.replace(/^\/why-academy/, '') || '/';
  location.replace('https://why-academy.gainullin.workers.dev' + path + location.search + location.hash);
})();
