import websocket, json, threading, time, logging, os
import os, sys, time, random, asyncio, json, logging, base64; 
from datetime import datetime; from typing import Dict, Tuple
import psutil; from aiohttp import ClientSession; 
from tasksio import TaskPool; from rich.table import Table
from rich.console import Console; from rich.highlighter import ReprHighlighter

application_path = os.getcwd()


logging.basicConfig(
    level=logging.INFO,
    format="\x1b[38;5;9m[\x1b[0m%(asctime)s\x1b[38;5;9m]\x1b[0m %(message)s\x1b[0m",
    datefmt="%H:%M:%S",
)

class Utils:
    def rangeCorrector(ranges):
        if [0, 99] not in ranges:
            ranges.insert(0, [0, 99])
        return ranges

    def getRanges(index, multiplier, memberCount):
        initialNum = int(index * multiplier)
        rangesList = [[initialNum, initialNum + 99]]
        if memberCount > initialNum + 99:
            rangesList.append([initialNum + 100, initialNum + 199])
        return Utils.rangeCorrector(rangesList)

    def parseGuildMemberListUpdate(response):
        memberdata = {
            "online_count": response["d"]["online_count"],
            "member_count": response["d"]["member_count"],
            "id": response["d"]["id"],
            "guild_id": response["d"]["guild_id"],
            "hoisted_roles": response["d"]["groups"],
            "types": [],
            "locations": [],
            "updates": [],
        }

        for chunk in response["d"]["ops"]:
            memberdata["types"].append(chunk["op"])
            if chunk["op"] in ("SYNC", "INVALIDATE"):
                memberdata["locations"].append(chunk["range"])
                if chunk["op"] == "SYNC":
                    memberdata["updates"].append(chunk["items"])
                else:  # invalidate
                    memberdata["updates"].append([])
            elif chunk["op"] in ("INSERT", "UPDATE", "DELETE"):
                memberdata["locations"].append(chunk["index"])
                if chunk["op"] == "DELETE":
                    memberdata["updates"].append([])
                else:
                    memberdata["updates"].append(chunk["item"])

        return memberdata


class DiscordSocket(websocket.WebSocketApp):
    def __init__(self, token, guild_id, channel_id):
        self.token = token
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.blacklisted_roles, self.blacklisted_users = [], []
        with open(f"{application_path}\data\config.json") as f:
            blacklisted = json.load(f)
        for i in blacklisted["blacklisted_roles"]:
            self.blacklisted_roles.append(str(i))
        for i in blacklisted["blacklisted_users"]:
            self.blacklisted_roles.append(str(i))

        self.socket_headers = {
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-WebSocket-Extensions": "permessage-deflate; client_max_window_bits",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:94.0) Gecko/20100101 Firefox/94.0",
        }

        super().__init__(
            "wss://gateway.discord.gg/?encoding=json&v=9",
            header=self.socket_headers,
            on_open=lambda ws: self.sock_open(ws),
            on_message=lambda ws, msg: self.sock_message(ws, msg),
            on_close=lambda ws, close_code, close_msg: self.sock_close(
                ws, close_code, close_msg
            ),
        )

        self.endScraping = False

        self.guilds = {}
        self.members = {}

        self.ranges = [[0, 0]]
        self.lastRange = 0
        self.packets_recv = 0

    def run(self):
        self.run_forever()
        return self.members

    def scrapeUsers(self):
        if self.endScraping == False:
            self.send(
                '{"op":14,"d":{"guild_id":"'
                + self.guild_id
                + '","typing":true,"activities":true,"threads":true,"channels":{"'
                + self.channel_id
                + '":'
                + json.dumps(self.ranges)
                + "}}}"
            )

    def sock_open(self, ws):
        # print("[Gateway]", "Connected to WebSocket.")
        self.send(
            '{"op":2,"d":{"token":"'
            + self.token
            + '","capabilities":125,"properties":{"os":"Windows","browser":"Firefox","device":"","system_locale":"it-IT","browser_user_agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:94.0) Gecko/20100101 Firefox/94.0","browser_version":"94.0","os_version":"10","referrer":"","referring_domain":"","referrer_current":"","referring_domain_current":"","release_channel":"stable","client_build_number":103981,"client_event_source":null},"presence":{"status":"online","since":0,"activities":[],"afk":false},"compress":false,"client_state":{"guild_hashes":{},"highest_last_message_id":"0","read_state_version":0,"user_guild_settings_version":-1,"user_settings_version":-1}}}'
        )

    def heartbeatThread(self, interval):
        try:
            while True:
                # print("sending heartbeat")
                self.send('{"op":1,"d":' + str(self.packets_recv) + "}")
                time.sleep(interval)
        except Exception as e:
            pass  # print(e)
            return  # returns when socket is closed

    def sock_message(self, ws, message):
        decoded = json.loads(message)

        if decoded is None:
            return

        if decoded["op"] != 11:
            self.packets_recv += 1

        if decoded["op"] == 10:
            threading.Thread(
                target=self.heartbeatThread,
                args=(decoded["d"]["heartbeat_interval"] / 1000,),
                daemon=True,
            ).start()

        if decoded["t"] == "READY":
            for guild in decoded["d"]["guilds"]:
                self.guilds[guild["id"]] = {"member_count": guild["member_count"]}

        if decoded["t"] == "READY_SUPPLEMENTAL":
            self.ranges = Utils.getRanges(
                0, 100, self.guilds[self.guild_id]["member_count"]
            )
            # print(self.ranges)
            self.scrapeUsers()

        elif decoded["t"] == "GUILD_MEMBER_LIST_UPDATE":
            parsed = Utils.parseGuildMemberListUpdate(decoded)

            if parsed["guild_id"] == self.guild_id and (
                "SYNC" in parsed["types"] or "UPDATE" in parsed["types"]
            ):
                for elem, index in enumerate(parsed["types"]):
                    if index == "SYNC":
                        # and parsed['locations'][elem] in self.ranges[1:]: #checks if theres nothing in the SYNC data
                        if len(parsed["updates"][elem]) == 0:
                            self.endScraping = True
                            break

                        for item in parsed["updates"][elem]:
                            if "member" in item:
                                # print(f"item: {item}")
                                mem = item["member"]
                                # print(f"mem: {mem}")
                                obj = {
                                    "tag": mem["user"]["username"]
                                    + "#"
                                    + mem["user"]["discriminator"],
                                    "id": mem["user"]["id"],
                                }
                                if not set(self.blacklisted_roles).isdisjoint(
                                    mem["roles"]
                                ):
                                    logging.info(
                                        f"{mem['user']['username'] + '#' + mem['user']['discriminator']} has a blacklisted role"
                                    )
                                else:
                                    if not mem["user"].get("bot"):
                                        if (
                                            not mem["user"]["id"]
                                            in self.blacklisted_users
                                        ):
                                            self.members[mem["user"]["id"]] = obj
                                        else:
                                            logging.info(
                                                f"{mem['user']['username'] + '#' + mem['user']['discriminator']} is a blacklisted user"
                                            )
                                    else:
                                        logging.info(
                                            f"{mem['user']['username'] + '#' + mem['user']['discriminator']} is a bot"
                                        )

                    elif index == "UPDATE":
                        for item in parsed["updates"][elem]:
                            if "member" in item:
                                # print(f"item: {item}")
                                mem = item["member"]
                                # print(f"mem: {mem}")
                                obj = {
                                    "tag": mem["user"]["username"]
                                    + "#"
                                    + mem["user"]["discriminator"],
                                    "id": mem["user"]["id"],
                                }
                                if not set(self.blacklisted_roles).isdisjoint(
                                    mem["roles"]
                                ):
                                    logging.info(
                                        f"{mem['user']['username'] + '#' + mem['user']['discriminator']} has a blacklisted role"
                                    )
                                else:
                                    if not mem["user"].get("bot"):
                                        if (
                                            not mem["user"]["id"]
                                            in self.blacklisted_users
                                        ):
                                            self.members[mem["user"]["id"]] = obj
                                        else:
                                            logging.info(
                                                f"{mem['user']['username'] + '#' + mem['user']['discriminator']} is a blacklisted user"
                                            )
                                    else:
                                        logging.info(
                                            f"{mem['user']['username'] + '#' + mem['user']['discriminator']} is a bot"
                                        )

                                # print("<SYNC>", "synced", mem["user"]["id"])
                                # print("<SYNC>", "synced", mem["user"])

                    print(self.endScraping)
                    print(self.ranges)
                    print("parsed", len(self.members))

                    self.lastRange += 1
                    self.ranges = Utils.getRanges(
                        self.lastRange, 100, self.guilds[self.guild_id]["member_count"]
                    )
                    time.sleep(0.35)
                    self.scrapeUsers()

            if self.endScraping:
                self.close()

    def sock_close(self, ws, close_code, close_msg):
        pass  # print("closed connection", close_code, close_msg)


def scrape(token, guild_id, channel_id):
    sb = DiscordSocket(token, guild_id, channel_id)
    return sb.run()


logging.basicConfig(
    level=logging.INFO,
    format="\x1b[38;5;9m[\x1b[0m%(asctime)s\x1b[38;5;9m]\x1b[0m %(message)s\x1b[0m",
    datefmt="%H:%M:%S"
)

class Discord(object):

    def __init__(self):
        if os.name == 'nt':
            self.clear = lambda: os.system("cls")
        else:
            self.clear = lambda: os.system("clear")

        self.clear()
        self.tokens = []
        self.blacklisted_users = []
        self.users = []

        self.guild_name = None
        self.guild_id = None
        self.channel_id = None
        self.g = "\033[92m"
        self.red = "\x1b[38;5;9m"
        self.rst = "\x1b[0m"
        self.success = f"{self.g}[+]{self.rst} "
        self.err = f"{self.red}[{self.rst}!{self.red}]{self.rst} "
        self.opbracket = f"{self.red}({self.rst}"
        self.opbracket2 = f"{self.g}[{self.rst}"
        self.closebrckt = f"{self.red}){self.rst}"
        self.closebrckt2 = f"{self.g}]{self.rst}"
        self.question = "\x1b[38;5;9m[\x1b[0m?\x1b[38;5;9m]\x1b[0m "
        self.arrow = f" {self.red}->{self.rst} "
        with open(f"{application_path}\data\{'useragents.txt'}", encoding="utf-8") as f:
            self.useragents = [i.strip() for i in f]

        try:
            with open(f"{application_path}\data\{'tokens.json'}", "r") as file:
                tkns = json.load(file)
                if len(tkns) == 0:
                    logging.info(f"{self.err} Please insert your tokens {self.opbracket}tokens.json{self.closebrckt}")
                    sys.exit()
                for tkn in tkns:
                    self.tokens.append(tkn)

        except Exception:
            logging.info(f"{self.err} Please insert your tokens correctly in {self.opbracket}tokens.json{self.closebrckt}")
            sys.exit()
        try:
            with open(f"{application_path}\data\message.json", "r") as file:
                data = json.load(file)
            msg = data['content']
        except Exception:
            logging.info(
                f"{self.err} Please insert your message correctly in {self.opbracket}message.json{self.closebrckt}\nRead the wiki if you need examples")
            sys.exit()
        try:
            with open(f"{application_path}\data\config.json", "r") as file:
                config = json.load(file)
                for user in config["blacklisted_users"]:
                    self.blacklisted_users.append(str(user))
                self.send_embed = config["send_embed"]
                self.send_message = config["send_normal_message"]
                not_counter = 0
                if not self.send_embed:
                    not_counter += 1
                    self.embd = ""
                else:
                    logging.info(f"{self.g}[+]{self.rst} Build your embed link at {self.red}https://embed.rauf.wtf/{self.rst}")
                    self.embd = input(f"{self.question}Embed Link{self.arrow}")
                    self.hide = input(f"{self.question}Should the Embed link be hidden? (This will increase the message lenght by 1k characters, but the link will be invisible)\n(y/n){self.arrow}")
                    if self.hide.lower() == "y":
                        self.embd = f"\n ||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||__ {self.embd}"
                    else:
                        self.embd = f"\n{self.embd}"
                if not self.send_message:
                    not_counter += 1
                    msg = ""
                if not_counter == 2:
                    logging.info(f"{self.err} You can\'t set send message and send embed to false {self.opbracket}config.json{self.closebrckt}.\nIf you do this you would try to send an empty message\nRead the wiki if you need help")
                    sys.exit()
        except Exception:
            logging.info(
                f"{self.err} Please insert the configuration stuff correctly {self.opbracket}config.json{self.closebrckt}.\nRead the wiki if you need help")
            sys.exit()
        with open(f"{application_path}\data\proxies.txt", encoding="utf-8") as f:
            self.proxies = [i.strip() for i in f]

        logging.info(
            f"{self.g}[+]{self.rst} Successfully loaded {self.red}%s{self.rst} token(s)\n" % (len(self.tokens)))
        self.invite = input(f"{self.question}Invite{self.arrow}discord.gg/").replace("/", "").replace("discord.com", "").replace("discord.gg", "").replace("invite", "").replace("https:", "").replace("http:", "").replace("discordapp.com", "")
        self.leaving = input(f"{self.question}Leave Server after Mass DM? {self.opbracket}y/n{self.closebrckt}{self.arrow}")
        self.mode = input(f"{self.question}Use Proxies? {self.opbracket}y/n{self.closebrckt}{self.arrow}")
        if self.mode.lower() == "y":
            self.use_proxies = True
            self.proxy_typee = input(f"{self.opbracket2}1{self.closebrckt2} http   | {self.opbracket2}2{self.closebrckt2} https\n{self.opbracket2}3{self.closebrckt2} socks4 | {self.opbracket2}4{self.closebrckt2} socks5\n{self.question}Proxy type{self.arrow}")
            if self.proxy_typee == "1":
                self.proxy_type = "http"
            elif self.proxy_typee == "2":
                self.proxy_type = "https"
            elif self.proxy_typee == "3":
                self.proxy_type = "socks4"
            elif self.proxy_typee == "4":
                self.proxy_type = "socks5"
            else: self.use_proxies = False
        else:
            self.use_proxies = False

        self.message = msg
        self.embed = self.embd
        try:
            self.delay = float(input(f"{self.question}Delay{self.arrow}"))
        except Exception:
            self.delay = 5
        try:
            self.ratelimit_delay = float(input(f"{self.question}Rate limit Delay{self.arrow}"))
        except Exception:
            self.ratelimit_delay = 300
        self.total_tokens = len(self.tokens)
        self.invalid_tokens_start = 0
        self.locked_tokens_start = 0
        self.locked_tokens_total = 0
        self.invalid_tokens_total = 0
        self.valid_tokens_start = 0
        self.valid_tokens_end = 0
        self.total_rate_limits = 0
        self.total_server_joins_success = 0
        self.total_server_joins_locked = 0
        self.total_server_joins_invalid = 0
        self.total_dms_success = 0
        self.total_dms_fail = 0
        self.invalid_token_dm = 0
        self.locked_token_dm = 0
        self.total_server_leave_success = 0
        self.total_server_leave_locked = 0
        self.total_server_leave_invalid = 0

        print()

    def stop(self):
        process = psutil.Process(os.getpid())
        process.terminate()

    def nonce(self):
        date = datetime.now()
        unixts = time.mktime(date.timetuple())
        return str((int(unixts) * 1000 - 1420070400000) * 4194304)

    async def headers(self, token):
        async with ClientSession() as client:
            async with client.get("https://discord.com/app") as response:
                cookies = str(response.cookies)
                dcfduid = cookies.split("dcfduid=")[1].split(";")[0]
                sdcfduid = cookies.split("sdcfduid=")[1].split(";")[0]
            async with client.get("https://discordapp.com/api/v9/experiments") as finger:
                json = await finger.json()
                fingerprint = json["fingerprint"]
            #logging.info(f"{self.success}Obtained dcfduid cookie: {dcfduid}")
            #logging.info(f"{self.success}Obtained sdcfduid cookie: {sdcfduid}")
            #logging.info(f"{self.success}Obtained fingerprint: {fingerprint}")
        useragent = random.choice(self.useragents)
        if "Windows" in useragent: device = "Windows"
        elif "Macintosh" in useragent: device = "Mac OS X"
        elif "Linux" in useragent: device = "Ubuntu"
        elif "iPad" in useragent: device = "iPadOS"
        elif "iPhone" in useragent: device = "iOS"
        elif "Android" in useragent: device = "Android 11"
        elif "X11" in useragent: device = "Unix"
        elif "iPod" in useragent: device = "iOS"
        elif "PlayStation" in useragent: device = "Orbis OS"
        else: device = "hoeOS"

        decoded_superproperty = '{"os":"%s","browser":"Discord Client","release_channel":"stable","client_version":"0.0.264","os_version":"15.6.0","os_arch":"x64","system_locale":"en-US","client_build_number":108924,"client_event_source":null}' % (device)
        message_bytes = decoded_superproperty.encode('ascii')
        base64_bytes = base64.b64encode(message_bytes)
        x_super_property = base64_bytes.decode('ascii')

        return {
            "Authorization": token,
            "accept": "*/*",
            "accept-language": "en-US",
            "connection": "keep-alive",
            "cookie": "__dcfduid=%s; __sdcfduid=%s; locale=en-US" % (dcfduid, sdcfduid),
            "DNT": "1",
            "origin": "https://discord.com",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "referer": "https://discord.com/channels/@me",
            "TE": "Trailers",
            "User-Agent": useragent,
            "x-debug-options": "bugReporterEnabled",
            "x-fingerprint": fingerprint,
            "X-Super-Properties": x_super_property
        }

    async def login(self, token: str, proxy: str):
        try:
            headers = await self.headers(token)
            async with ClientSession(headers=headers) as mass_dm_brrr:
                async with mass_dm_brrr.get("https://discord.com/api/v9/users/@me/library", proxy=proxy) as response:
                    try:
                        json = await response.json()
                        jsoncode = json["code"]
                        code = f"{self.opbracket}{jsoncode}{self.closebrckt} | "
                    except:
                        code = ""
                    if response.status == 200:
                        logging.info(
                            f"{self.success}Successfully logged in {code}{self.opbracket}%s{self.closebrckt}" % (token[:59]))
                        self.valid_tokens_start += 1
                    if response.status == 401:
                        logging.info(f"{self.err}Invalid account {code}{self.opbracket}%s{self.closebrckt}" % (token[:59]))
                        self.invalid_tokens_start += 1
                        self.tokens.remove(token)
                    if response.status == 403:
                        logging.info(f"{self.err}Locked account {code}{self.opbracket}%s{self.closebrckt}" % (token[:59]))
                        self.locked_tokens_start += 1
                        self.tokens.remove(token)
                    if response.status == 429:
                        logging.info(f"{self.err}Rate limited {code}{self.opbracket}%s{self.closebrckt}" % (token[:59]))
                        time.sleep(self.ratelimit_delay)
                        self.total_rate_limits += 1
                        await self.login(token, proxy)
        except Exception:
            await self.login(token, proxy)

    async def join(self, token: str, proxy: str):
        try:
            headers = await self.headers(token)
            async with ClientSession(headers=headers) as hoemotion:
                async with hoemotion.post("https://discord.com/api/v9/invites/%s" % (self.invite), json={}, proxy=proxy) as response:
                    json = await response.json()
                    if response.status == 200:
                        self.guild_name = json["guild"]["name"]
                        self.guild_id = json["guild"]["id"]
                        self.channel_id = json["channel"]["id"]
                        logging.info(f"{self.success}Successfully joined %s {self.opbracket}%s{self.closebrckt}" % (
                        self.guild_name[:20], token[:59]))
                        self.total_server_joins_success += 1
                    elif response.status == 401:
                        logging.info(f"{self.err}Invalid account {self.opbracket}%s{self.closebrckt}" % (token[:59]))
                        self.tokens.remove(token)
                        self.total_server_joins_invalid += 1
                    elif response.status == 403:
                        logging.info(f"{self.err}Locked account {self.opbracket}%s{self.closebrckt}" % (token[:59]))
                        self.total_server_joins_locked += 1
                        self.tokens.remove(token)
                    elif response.status == 429:
                        logging.info(f"{self.err}Rate limited {self.opbracket}%s{self.closebrckt}" % (token[:59]))
                        self.total_rate_limits += 1
                        time.sleep(self.ratelimit_delay)
                        await self.join(token, proxy)
                    elif response.status == 404:
                        logging.info(f"{self.err}Server-Invite is invalid or has expired :/")
                        self.stop()
                    else:
                        self.tokens.remove(token)
        except Exception:
            await self.join(token, proxy)

    async def create_dm(self, token: str, user: str, proxy: str):
        try:
            headers = await self.headers(token)
            async with ClientSession(headers=headers) as chupapi_munanyo:
                async with chupapi_munanyo.post("https://discord.com/api/v9/users/@me/channels",
                                                json={"recipients": [user]}, proxy=proxy) as response:
                    json = await response.json()
                    if response.status == 200:
                        logging.info(
                            f"{self.success}Successfully created direct message with %s {self.opbracket}%s{self.closebrckt}" % (
                            json["recipients"][0]["username"], token[:59]))
                        return json["id"]
                    elif response.status == 401:
                        logging.info(f"{self.err}Invalid account {self.opbracket}%s{self.closebrckt}" % (token[:59]))
                        self.invalid_tokens_total += 1
                        self.tokens.remove(token)
                        return False
                    elif response.status == 403:
                        logging.info(
                            f"{self.err}Can\'t message user {self.opbracket}%s{self.closebrckt}" % (token[:59]))
                        self.tokens.remove(token)
                    elif response.status == 429:
                        logging.info(f"{self.err}Rate limited {self.opbracket}%s{self.closebrckt}" % (token[:59]))
                        self.total_rate_limits += 1
                        time.sleep(self.ratelimit_delay)
                        return await self.create_dm(token, user, proxy)
                    elif response.status == 400:
                        logging.info(
                            f"{self.err}Can\'t create DM with yourself! {self.opbracket}%s{self.closebrckt}" % (
                            token[:59]))
                    elif response.status == 404:
                        logging.info(
                            f"{self.err}User doesn\'t exist! {self.opbracket}%s{self.closebrckt}" % (token[:59]))
                    else:
                        return False
        except Exception:
            return await self.create_dm(token, user, proxy)

    async def direct_message(self, token: str, channel: str, user, proxy: str):
        embed = self.embed
        message = self.get_user_in_message(user)
        headers = await self.headers(token)
        async with ClientSession(headers=headers) as virgin:
            async with virgin.post("https://discord.com/api/v9/channels/%s/messages" % (channel),
                                   json={"content": f"{message}{embed}", "nonce": self.nonce(),
                                         "tts": False}, proxy=proxy) as response:
                json = await response.json()
                if response.status == 200:
                    logging.info(f"{self.success}Successfully sent message {self.opbracket}%s{self.red}){self.rst}" % (
                    token[:59]))
                    self.total_dms_success += 1
                elif response.status == 401:
                    logging.info(f"{self.err}Invalid account {self.opbracket}%s{self.closebrckt}" % (token[:59]))
                    self.tokens.remove(token)
                    self.invalid_tokens_total += 1
                    self.invalid_token_dm += 1
                    return False
                elif response.status == 403 and json["code"] == 40003:
                    logging.info(f"{self.err}Rate limited {self.opbracket}%s{self.closebrckt}" % (token[:59]))
                    time.sleep(self.ratelimit_delay)
                    self.total_rate_limits += 1
                    await self.direct_message(token, channel, user, proxy)
                elif response.status == 403 and json["code"] == 50007:
                    logging.info(f"{self.err}User has direct messages disabled {self.opbracket}%s{self.closebrckt}" % (
                    token[:59]))
                elif response.status == 403 and json["code"] == 40002:
                    logging.info(f"{self.err}Locked {self.opbracket}%s{self.closebrckt}" % (token[:59]))
                    self.locked_token_dm += 1
                    self.locked_tokens_total += 1
                    self.tokens.remove(token)
                    return False
                elif response.status == 429:
                    logging.info(f"{self.err}Rate limited {self.opbracket}%s{self.closebrckt}" % (token[:59]))
                    time.sleep(self.ratelimit_delay)
                    self.total_rate_limits += 1
                    await self.direct_message(token, channel, user, proxy)
                elif response.status == 400:
                    code = json["code"]
                    logging.info(f"{self.err}Can\'t DM this User! {self.opbracket}{code}{self.closebrckt} | {self.opbracket}%s{self.closebrckt}" % (token[:59]))
                elif response.status == 404:
                    logging.info(f"{self.err}User doesn\'t exist! {self.opbracket}%s{self.closebrckt}" % (token[:59]))
                else:
                    return False

    def get_user_in_message(self, user: str = None):
        mssage = self.message
        message = mssage.replace("<user>", f"<@{user}>")
        return message



    async def send(self, token: str, user: str, proxy: str):
        channel = await self.create_dm(token, user, proxy)
        if channel == False:
            return await self.send(random.choice(self.tokens), user, proxy)
        response = await self.direct_message(token, channel, user, proxy)
        if response == False:
            return await self.send(random.choice(self.tokens), user, proxy)

    async def leave(self, token: str, proxy: str):
        try:
            headers = await self.headers(token)
            async with ClientSession(headers=headers) as client:
                async with client.delete(f"https://discord.com/api/v9/users/@me/guilds/{self.guild_id}",
                                         json={"lurking": False}, proxy=proxy) as response:
                    json = await response.json()
                    message = json["message"]
                    code = json["code"]
                    if response.status == 200:
                        logging.info(
                            f"{self.success}Successfully left the Guild {self.opbracket}%s{self.closebrckt}" % (
                            token[:59]))
                        self.total_server_leave_success += 1
                    elif response.status == 204:
                        logging.info(
                            f"{self.success}Successfully left the Guild {self.opbracket}%s{self.closebrckt}" % (
                            token[:59]))
                        self.total_server_leave_success += 1
                    elif response.status == 404:
                        logging.info(
                            f"{self.success}Successfully left the Guild {self.opbracket}%s{self.closebrckt}" % (
                            token[:59]))
                        self.total_server_leave_success += 1
                    elif response.status == 403:
                        self.total_server_leave_locked += 1
                        logging.info(f"{self.err}{message} | {code} {self.opbracket}%s{self.closebrckt}" % (token[:59]))
                    elif response.status == 401:
                        self.total_server_leave_invalid += 1
                        self.locked_tokens_total += 1
                        logging.info(f"{self.err}{message} | {code} {self.opbracket}%s{self.closebrckt}" % (token[:59]))
                    elif response.status == 429:
                        self.total_rate_limits += 1
                        logging.info(f"{self.err}{message} | {code} {self.opbracket}%s{self.closebrckt}" % (token[:59]))
                        time.sleep(self.ratelimit_delay)
                        await self.leave(token, proxy)
                    else:
                        logging.info(
                            f"{self.err}{response.status} | {message} | {code} | {self.opbracket}%s{self.closebrckt}" % (
                            token[:59]))

        except Exception:
            await self.leave(token, proxy)

    async def start(self):
        if len(self.tokens) == 0:
            logging.info("No tokens loaded.")
            sys.exit()

        def table():

            table = Table(
                title=f"Total Users Scraped: {len(self.users)}",
                caption="Discord: pushkar#8774",
                caption_justify="right",
                caption_style="bright_yellow"
            )

            table.add_column("Tokens", header_style="bright_cyan", style="blue", no_wrap=True)
            table.add_column("Login Details", header_style="bright_magenta", style="magenta", justify="center")
            table.add_column("Join Details", justify="center", header_style="light_green", style="bright_green")
            table.add_column("DM Users", justify="center", header_style="magenta", style="blue")
            table.add_column("Leave Details", justify="center", header_style="bright_cyan", style="bright_green")

            table.add_row(
                f"[Total] Tokens: {self.total_tokens}",
                f"[Login] Valid Tokens: {self.valid_tokens_start}",
                f"[Join] Valid Tokens: {self.total_server_joins_success}",
                f"[DM] Total DMed: {self.total_dms_success}\n[DM] Total Failed: {self.total_dms_fail}",
                f"[Leave] Tokens Left Successfully: {self.total_server_leave_success}",
                style="on black",
                end_section=True,
            )
            table.add_row(
                f"[Total] Tokens Invalid: {self.invalid_tokens_total}",
                f"[Login] Tokens Invalid: {self.invalid_tokens_start}",
                f"[Join] Tokens Invalid: {self.total_server_joins_invalid}",
                f"[DM] Tokens Invalid: {self.invalid_token_dm}",
                f"[Leave] Tokens Invalid: {self.total_server_leave_invalid}",
                style="on black",
                end_section=True,
            )
            table.add_row(
                f"[Total] Tokens Locked: {self.locked_tokens_total}",
                f"[Login] Tokens Locked: {self.locked_tokens_start}",
                f"[Join] Tokens Locked: {self.total_server_joins_locked}",
                f"[DM] Tokens Locked: {self.locked_token_dm}",
                f"[Leave] Tokens Locked: {self.total_server_leave_locked}",
                style="on black",
                end_section=True,
            )

            def header(text: str) -> None:
                console.print()
                console.rule(highlight(text))
                console.print()

            console = Console()
            highlight = ReprHighlighter()

            table.width = None
            table.expand = False
            table.row_styles = ["dim", "none"]
            table.show_lines = True
            table.leading = 0
            header("MassDM analytics")
            console.print(table, justify="center")
            return

        async with TaskPool(1_000) as pool:
            for token in self.tokens:
                if len(self.tokens) != 0:
                    if self.use_proxies:
                        proxy = "%s://%s" % (self.proxy_type, random.choice(self.proxies))
                    else:
                        proxy = None
                    await pool.put(self.login(token, proxy))
                else:
                    self.stop()

        if len(self.tokens) == 0:
            self.stop()

        print()
        logging.info("Joining server.")
        print()

        async with TaskPool(1_000) as pool:
            for token in self.tokens:
                if len(self.tokens) != 0:
                    if self.use_proxies:
                        proxy = "%s://%s" % (self.proxy_type, random.choice(self.proxies))
                    else:
                        proxy = None
                    await pool.put(self.join(token, proxy))
                    if self.delay != 0: await asyncio.sleep(self.delay)
                else:
                    self.stop()

        if len(self.tokens) == 0:
            self.stop()

        print()
        logging.info("Scraping Users...\nPlease be patient")
        print()


        members = scrape(self.tokens[0], self.guild_id, self.channel_id)
        for member in members:
            if member not in self.users:
                self.users.append(member)


        print()
        logging.info(f"Successfully scraped {self.red}%s{self.rst} members" % (len(self.users)))
        logging.info("Sending messages.")
        print()

        if len(self.tokens) == 0: self.stop()

        async with TaskPool(1_000) as pool:
            for user in self.users:
                if len(self.tokens) != 0:
                    if str(user) not in self.blacklisted_users:
                        if self.use_proxies:
                            proxy = "%s://%s" % (self.proxy_type, random.choice(self.proxies))
                        else:
                            proxy = None
                        await pool.put(self.send(random.choice(self.tokens), user, proxy))
                        if self.delay != 0: await asyncio.sleep(self.delay)
                    else:
                        logging.info(f"{self.err}Blacklisted User: {self.red}%s{self.rst}" % (user))
                else:
                    table()
                    self.stop()

        if self.leaving == "y":
            print()
            logging.info("Leaving %s" % self.guild_name)
            print()
            async with TaskPool(1_000) as pool:
                if len(self.tokens) != 0:
                    for token in self.tokens:
                        if self.use_proxies:
                            proxy = "%s://%s" % (self.proxy_type, random.choice(self.proxies))
                        else:
                            proxy = None
                        await pool.put(self.leave(token, proxy))
                        if self.delay != 0:
                            await asyncio.sleep(self.delay)
                    logging.info("All Tasks are done")
                    table()
                    self.stop()
                else:
                    table()
                    self.stop()
        else:
            logging.info("All Tasks are done")
            table()
            self.stop()

if __name__ == "__main__":
    client = Discord()
    asyncio.get_event_loop().run_until_complete(client.start())


