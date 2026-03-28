"""Bloqueur de publicités pour QWebEngineView.

Intercepte les requêtes réseau et bloque les domaines publicitaires
connus. Léger et efficace — pas de liste externe à télécharger.

Usage dans fenetre_principale.py :
    from ui.ad_blocker import installer_bloqueur
    installer_bloqueur(self._webview)
"""

from PySide6.QtWebEngineCore import (
    QWebEngineUrlRequestInterceptor,
    QWebEngineUrlRequestInfo,
)

# Domaines publicitaires courants (WordReference + génériques)
_DOMAINES_BLOQUES = {
    # Réseaux publicitaires
    "doubleclick.net",
    "googlesyndication.com",
    "googleadservices.com",
    "google-analytics.com",
    "googletagmanager.com",
    "googletagservices.com",
    "pagead2.googlesyndication.com",
    "adservice.google.com",
    "adscdn.net",
    "ads.pubmatic.com",
    "pubmatic.com",
    "adnxs.com",
    "adsrvr.org",
    "adform.net",
    "advertising.com",
    "rubiconproject.com",
    "casalemedia.com",
    "criteo.com",
    "criteo.net",
    "outbrain.com",
    "taboola.com",
    "amazon-adsystem.com",
    "moatads.com",
    "serving-sys.com",
    "bidswitch.net",
    "openx.net",
    "sharethrough.com",
    "indexexchange.com",
    "33across.com",
    "smartadserver.com",
    "quantserve.com",
    "scorecardresearch.com",
    "bluekai.com",
    "exelator.com",
    "rlcdn.com",
    "demdex.net",
    "krxd.net",
    "turn.com",
    "contextweb.com",
    "yieldmo.com",
    "sovrn.com",
    "lijit.com",
    "media.net",
    "medianet.com",

    # Trackers
    "facebook.net",
    "fbcdn.net",
    "connect.facebook.net",
    "twitter.com",
    "platform.twitter.com",
    "analytics.twitter.com",
    "hotjar.com",
    "newrelic.com",
    "nr-data.net",
    "sentry.io",
    "segment.io",
    "segment.com",
    "mixpanel.com",
    "amplitude.com",
    "optimizely.com",
    "chartbeat.com",

    # Consent / cookie banners
    "cookielaw.org",
    "cookiebot.com",
    "onetrust.com",
    "trustarc.com",
    "consensu.org",
    "quantcast.com",

    # WordReference spécifiques
    "cdn.privacy-mgmt.com",
    "privacy-mgmt.com",
    "sp-prod.net",
}

# Mots-clés dans l'URL qui indiquent une pub
_MOTS_CLES_PUB = {
    "/ads/", "/adserv", "/advert", "/banner",
    "/sponsor", "/pixel", "/tracking", "/beacon",
    "pagead", "adsense", "dfp_", "prebid",
}


class _BlocPub(QWebEngineUrlRequestInterceptor):
    """Intercepteur qui bloque les requêtes vers des domaines publicitaires."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nb_bloques = 0

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        url = info.requestUrl()
        host = url.host().lower()
        path = url.toString().lower()

        # Vérifier le domaine
        for domaine in _DOMAINES_BLOQUES:
            if host == domaine or host.endswith("." + domaine):
                info.block(True)
                self._nb_bloques += 1
                return

        # Vérifier les mots-clés dans l'URL
        for mot in _MOTS_CLES_PUB:
            if mot in path:
                info.block(True)
                self._nb_bloques += 1
                return

    @property
    def nb_bloques(self) -> int:
        return self._nb_bloques


# Singleton
_instance: _BlocPub | None = None


def installer_bloqueur(webview) -> None:
    """Installe le bloqueur sur le profil du QWebEngineView.

    À appeler une seule fois après la création du webview.
    """
    global _instance

    try:
        from PySide6.QtWebEngineCore import QWebEngineProfile

        profile = webview.page().profile()
        if _instance is None:
            _instance = _BlocPub(profile)
        profile.setUrlRequestInterceptor(_instance)
        print("[AdBlock] Bloqueur installé")
    except Exception as e:
        print(f"[AdBlock] Erreur installation: {e}")
