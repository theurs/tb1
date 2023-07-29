from time import sleep
from uuid import uuid4
from requests import Session
from threading import Thread
from json import loads, dumps
from random import getrandbits
from websocket import WebSocketApp

from Answer import Answer, Details

import logging, traceback
logger = logging.getLogger()


from urllib.parse import urlparse




class Perplexity:
    """A class to interact with the Perplexity website.
    To get started you need to create an instance of this class.
    For now this class only support one Answer at a time.
    """
    def __init__(self, proxy = None) -> None:

        self.proxies = proxy

        self.ws_connecting = False
        self.ws_connected = False
        self.user_agent: dict = { "User-Agent": "" }
        self.session: Session = self.init_session()

        self.searching = False
        self.t: str = self.get_t()
        self.answer: Answer = None
        self.ask_for_details = False
        self.sid: str = self.get_sid()
        self.frontend_uuid = str(uuid4())
        self.frontend_session_id = str(uuid4())

        assert self.ask_anonymous_user(), "Failed to ask anonymous user"
        self.ws = None
        self.init_websocket()
        self.n = 1
        self.auth_session()

        sleep(1)

    def init_session(self) -> Session:
        session: Session = Session()

        uuid: str = str(uuid4())
        session.get(url=f"https://www.perplexity.ai/search/{uuid}", headers=self.user_agent, proxies=self.proxies)

        return session
    
    def get_t(self) -> str:
        return format(getrandbits(32), "08x")

    def get_sid(self) -> str:
        r = self.session.get(
            url=f"https://www.perplexity.ai/socket.io/?EIO=4&transport=polling&t={self.t}",
            headers=self.user_agent,
            proxies=self.proxies)
        # import my_log
        # my_log.log2(str(r))
        response = loads(r.text[1:])

        return response["sid"]

    def ask_anonymous_user(self) -> bool:
        response = self.session.post(
            url=f"https://www.perplexity.ai/socket.io/?EIO=4&transport=polling&t={self.t}&sid={self.sid}",
            data="40{\"jwt\":\"anonymous-ask-user\"}",
            headers=self.user_agent,
            proxies=self.proxies
        ).text

        return response == "OK"

    def on_message(self, ws: WebSocketApp, message: str) -> None:
        try:
            if message == "2":
                ws.send("3")
            elif message == "3probe":
                ws.send("5")

            if (self.searching or self.ask_for_details) and message.startswith(str(430 + self.n)):
                response = loads(message[3:])[0]

                if self.searching:
                    self.answer = Answer(
                        uuid=response["uuid"],
                        gpt4=response["gpt4"],
                        text=response["text"],
                        search_focus=response["search_focus"],
                        backend_uuid=response["backend_uuid"],
                        query_str=response["query_str"],
                        related_queries=response["related_queries"]
                    )
                    self.searching = False
                else:
                    self.answer.details = Details(
                        uuid=response["uuid"],
                        text=response["text"]
                    )
                    self.ask_for_details = False
        except:
            logger.error(traceback.format_exc())
            self.disconnect_ws()
            self.connect_ws()

    def get_cookies_str(self) -> str:
        cookies = ""
        for key, value in self.session.cookies.get_dict().items():
            cookies += f"{key}={value}; "
        return cookies[:-2]

    def init_websocket(self, timeout=5):
        if self.ws_connected:
            return
        if self.ws_connecting:
            while not self.ws_connected:
                sleep(0.01)
            return
        self.ws_connecting = True
        self.ws_connected = False
        
        ws = WebSocketApp(
            url=f"wss://www.perplexity.ai/socket.io/?EIO=4&transport=websocket&sid={self.sid}",
            header=self.user_agent,
            cookie=self.get_cookies_str(),
            on_open=lambda ws: self.on_ws_connect(ws),
            on_message=self.on_message,
            on_error=self.on_ws_error,
            on_close=self.on_ws_close
        )
        self.ws = ws

        if self.proxies:
            proxy_string = self.proxies['http']
            parsed_proxy = urlparse(proxy_string)
            p_type =        parsed_proxy.scheme
            p_user =        parsed_proxy.username
            p_password =    parsed_proxy.password
            p_host =        parsed_proxy.hostname
            p_port =        parsed_proxy.port
            my_args = (None, None, 0, None, "",
                       p_host, p_port, None,
                       (p_user, p_password),
                       None, False, None, None, None, False,
                       p_type, None)
            ws_thread: Thread = Thread(target=ws.run_forever, args = my_args)
        else:
            ws_thread: Thread = Thread(target=ws.run_forever)
        ws_thread.daemon = True
        ws_thread.start()

        timer = 0
        while not self.ws_connected:
            sleep(0.01)
            timer += 0.01
            if timer > timeout:
                self.ws_connecting = False
                self.ws_connected = False
                self.ws_error = True
                ws.close()
                raise RuntimeError("Timed out waiting for websocket to connect.")

    def disconnect_ws(self):
        self.ws_connecting = False
        self.ws_connected = False
        if self.ws:
            self.ws.close()

    def on_ws_connect(self, ws):
        self.ws_connecting = False
        self.ws_connected = True
        ws.send("2probe")

    def on_ws_close(self):
        self.ws_connecting = False
        self.ws_connected = False
        if self.ws_error:
            self.ws_error = False
            self.connect_ws()

    def on_ws_error(self, ws, error):
        self.ws_connecting = False
        self.ws_connected = False
        self.ws_error = True

    def auth_session(self) -> None:
        self.session.get(url="https://www.perplexity.ai/api/auth/session", headers=self.user_agent)

    def search(self, query: str, search_focus: str = "internet") -> Answer:
        """A function to search for a query. You can specify the search focus between: "internet", "scholar", "news", "youtube", "reddit", "wikipedia".
        Return the Answer object.
        """
        assert not self.searching, "Already searching"
        assert search_focus in ["internet", "scholar", "news", "youtube", "reddit", "wikipedia"], "Invalid search focus"
        self.searching = True
        self.n += 1
        ws_message: str = f"{420 + self.n}" + dumps([
            "perplexity_ask",
            query,
            {
                "source": "default",
                "last_backend_uuid": None,
                "read_write_token": "",
                "conversational_enabled": True,
                "frontend_session_id": self.frontend_session_id,
                "search_focus": search_focus,
                "frontend_uuid": self.frontend_uuid,
                "web_search_images": True,
                "gpt4": False
            }
        ])
        self.ws.send(ws_message)
        while self.searching:
            sleep(0.1)
        
        return self.answer

    def ask_detailed(self) -> Answer:
        """A function to ask for more details about the answer.
        Return the Answer object.
        """
        assert self.answer is not None, "Answer is None"
        assert not self.searching, "Already searching"

        self.ask_for_details = True
        self.n += 1
        ws_message: str = f"{420 + self.n}" + dumps([
            "perplexity_ask_detailed",
            self.answer.backend_uuid,
            {"frontend_uuid": str(uuid4())}
        ])
        self.ws.send(ws_message)
        while self.ask_for_details:
            sleep(0.1)
        
        return self.answer

