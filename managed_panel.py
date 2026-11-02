"""Dedicated browser context so Quit closes our dashboard without touching personal tabs."""
import hashlib
from urllib.parse import urlsplit

class ManagedPanel:
    def __init__(self,chromium,folder,launch_options):
        self.chromium=chromium;self.folder=folder;self.launch_options=launch_options
        self.context=None;self.page=None
    def open(self,url,selection):
        parsed=urlsplit(url or '')
        if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.username or not parsed.port or parsed.path not in ('','/'):
            raise ValueError('Панель ещё не готова.')
        if self.context:
            try:
                if self.page is None or self.page.is_closed():self.page=self.context.new_page();self.page.goto(url,wait_until='domcontentloaded',timeout=15000)
                self.page.bring_to_front();return
            except Exception:self.close()
        options=None
        # Only the LOCAL panel may use a fallback. Lecture browser selection is unchanged.
        for candidate in dict.fromkeys([selection,'edge','chrome','yandex']):
            try:options=self.launch_options(candidate);break
            except ValueError:continue
        if options is None:raise ValueError('Для панели установи Chrome, Edge или Яндекс. Личные профили не используются.')
        profile=hashlib.sha256(str(options).lower().encode()).hexdigest()[:12]
        try:
            self.context=self.chromium.launch_persistent_context(str(self.folder/'panel-profiles'/profile),headless=False,no_viewport=True,**options)
            self.page=self.context.pages[0] if self.context.pages else self.context.new_page()
            self.page.goto(url,wait_until='domcontentloaded',timeout=15000)
            self.page.bring_to_front()
        except Exception:self.close();raise
    def pump(self):
        if not self.context:return
        try:
            if self.page and not self.page.is_closed():self.page.wait_for_timeout(1)
        except Exception:self.close()
    def close(self):
        context=self.context;self.context=self.page=None
        if context:
            try:context.close()
            except Exception:pass
