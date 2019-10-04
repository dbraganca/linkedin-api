import requests
import pickle
import logging
import time
import os

import linkedin_api.settings as settings

logger = logging.getLogger(__name__)


class ChallengeException(Exception):
    pass


class UnauthorizedException(Exception):
    pass


class Client(object):
    """
    Class to act as a client for the Linkedin API.
    """

    # Settings for general Linkedin API calls
    API_BASE_URL = "https://www.linkedin.com/voyager/api"
    REQUEST_HEADERS = {
        "user-agent": " ".join(
            [
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_5)",
                "AppleWebKit/537.36 (KHTML, like Gecko)",
                "Chrome/66.0.3359.181 Safari/537.36",
            ]
        ),
        # "accept": "application/vnd.linkedin.normalized+json+2.1",
        "accept-language": "en-AU,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
        "x-li-lang": "en_US",
        "x-restli-protocol-version": "2.0.0",
        # "x-li-track": '{"clientVersion":"1.2.6216","osName":"web","timezoneOffset":10,"deviceFormFactor":"DESKTOP","mpName":"voyager-web"}',
    }

    # Settings for authenticating with Linkedin
    AUTH_BASE_URL = "https://www.linkedin.com"
    AUTH_REQUEST_HEADERS = {
        "X-Li-User-Agent": "LIAuthLibrary:3.2.4 \
                            com.linkedin.LinkedIn:8.8.1 \
                            iPhone:8.3",
        "User-Agent": "LinkedIn/8.8.1 CFNetwork/711.3.18 Darwin/14.0.0",
        "X-User-Language": "en",
        "X-User-Locale": "en_US",
        "Accept-Language": "en-us",
    }

    def __init__(self, *, debug=False, refresh_cookies=False, proxies={}):
        self.session = requests.session()
        self.session.proxies.update(proxies)
        self.session.headers.update(Client.REQUEST_HEADERS)
        self.proxies = proxies
        self.logger = logger
        self._use_cookie_cache = not refresh_cookies
        logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
        if not os.path.exists(settings.COOKIE_PATH):
            os.makedirs(settings.COOKIE_PATH)

    def _request_session_cookies(self):
        """
        Return a new set of session cookies as given by Linkedin.
        """
        res = requests.get(
            f"{Client.AUTH_BASE_URL}/uas/authenticate",
            headers=Client.AUTH_REQUEST_HEADERS,
            proxies=self.proxies
        )

        return res.cookies

    def _load_cookies_from_cache(self, username):
        try:
            cookiejar_file = self._get_cookiejar_file(username)
            with open(cookiejar_file, "rb") as f:
                cookies = pickle.load(f)
                if cookies:
                    return True, cookies

        except FileNotFoundError:
            self.logger.debug("Cookie file not found. Requesting new cookies.")

        return False, None

    def _get_cookiejar_file(self, username):
        """
        Return the absolute path of the cookiejar for a given username
        """
        return "{}{}.jr".format(settings.COOKIE_PATH, username)

    def _set_session_cookies(self, cookiejar, username):
        """
        Set cookies of the current session and save them to a file named as the username.
        """
        self.session.cookies = cookiejar
        self.session.headers["csrf-token"] = self.session.cookies["JSESSIONID"].strip(
            '"'
        )
        cookiejar_file = self._get_cookiejar_file(username)
        with open(cookiejar_file, "wb") as f:
            pickle.dump(cookiejar, f)

    @property
    def cookies(self):
        return self.session.cookies

    def _is_token_still_valid(self, cookies):

        _now = time.time()
        for cookie in cookies:
            if cookie.name == "JSESSIONID" and cookie.value:
                if cookie.expires and cookie.expires > _now:
                    return True
                break

        return False

    def authenticate(self, username, password):

        if self._use_cookie_cache:
            self.logger.debug("Attempting to use cached cookies")
            found, cookies = self._load_cookies_from_cache(username)
            if found and self._is_token_still_valid(cookies):
                return

        return self._do_authentication_request(username, password)

    def _do_authentication_request(self, username, password):
        """
        Authenticate with Linkedin.

        Return a session object that is authenticated.
        """
        self._set_session_cookies(self._request_session_cookies(), username)

        payload = {
            "session_key": username,
            "session_password": password,
            "JSESSIONID": self.session.cookies["JSESSIONID"],
        }

        res = requests.post(
            f"{Client.AUTH_BASE_URL}/uas/authenticate",
            data=payload,
            cookies=self.session.cookies,
            headers=Client.AUTH_REQUEST_HEADERS,
            proxies=self.proxies
        )

        data = res.json()

        if data and data["login_result"] != "PASS":
            raise ChallengeException(data["login_result"])

        if res.status_code == 401:
            raise UnauthorizedException()

        if res.status_code != 200:
            raise Exception()

        self._set_session_cookies(res.cookies, username)
