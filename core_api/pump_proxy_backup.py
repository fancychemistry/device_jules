"""pump_proxy.py  鈥? v3
Moonraker 锠曞姩娉?HTTP 灏佽锛屽甫缁撴灉杈撳嚭

涓嶮oonrakerWebsocketListener闆嗘垚锛屽疄鐜颁粠WebSocket鑾峰彇绮剧‘鐨勬车閫佸弬鏁般€?"""
import requests
import logging
import re
import json
import uuid
import asyncio
from typing import Dict, Any, Optional

log = logging.getLogger(__name__)

# 濡傛灉MoonrakerWebsocketListener绫诲湪鍗曠嫭鏂囦欢涓?try:
    from core_api.moonraker_listener import MoonrakerWebsocketListener
except ImportError:
    # 杩欏皢浣夸笅闈㈢殑绫诲瀷鎻愮ず鑳藉閫氳繃锛屼絾瀹為檯鍒濆鍖栨椂闇€瑕佹彁渚涙纭殑瀹炰緥
    MoonrakerWebsocketListener = Any


class MoonrakerError(RuntimeError):
    pass


class PumpProxy:
    def __init__(self, base_url: str, listener: Optional[MoonrakerWebsocketListener] = None):
        """鍒濆鍖栨车浠ｇ悊

        Args:
            base_url: Moonraker HTTP API鍩虹URL锛屼緥濡?"http://192.168.1.100:7125"
            listener: MoonrakerWebsocketListener瀹炰緥锛岀敤浜庢帴鏀舵车鏈嶅姟鐨勫弬鏁般€傚鏋滀负None锛屽皢浣跨敤浼犵粺鏂瑰紡浼扮畻鍙傛暟銆?        """
        self.base = base_url.rstrip('/')
        self.listener = listener  # WebSocket鐩戝惉鍣?        
        # 娉垫牎鍑嗗熀鍑嗗€硷紝鐢ㄤ簬浼扮畻鏃堕棿锛堜粎鍦ㄦ棤娉曚粠WebSocket鑾峰彇绮剧‘鍊兼椂浣跨敤锛?        self.fallback_calibration = {
            'slow': {'rpm': 5.0, 'ml_per_rev': 0.08},
            'normal': {'rpm': 20.0, 'ml_per_rev': 0.08},
            'fast': {'rpm': 60.0, 'ml_per_rev': 0.08},
        }
        # 姝ｅ垯琛ㄨ揪寮忕敤浜庤В鏋怭umpService鏃ュ織
        self.rpm_regex = re.compile(r"(?:閫夋嫨|璁惧畾|浣跨敤)(?:杞€焲閫熷害)[:锛歖\s*([\d\.]+)\s*(?:RPM|rpm)")
        self.revolutions_regex = re.compile(r"(?:闇€瑕亅灏唡瑕?(?:杞姩|鏃嬭浆)[:锛歖?\s*([\d\.]+)\s*(?:鍦坾杞?")

    # --- private ---
    async def _send_async(self, script: str):
        """鍚慚oonraker鍙戦€丟-code鑴氭湰鍛戒护锛堝紓姝ユ墽琛岋級

        Args:
            script: G-code鑴氭湰鍛戒护

        Returns:
            Dict: Moonraker鐨勫搷搴?        """
        url = f"{self.base}/printer/gcode/script"
        log.debug("POST (async) %s | %s", url, script)
        try:
            loop = asyncio.get_event_loop()
            # 浣跨敤 functools.partial 灏嗗弬鏁扮粦瀹氬埌鍚屾鍑芥暟
            # This makes self._blocking_post suitable for run_in_executor
            import functools
            partial_blocking_post = functools.partial(self._blocking_post, url, script)
            
            # 鍦╡xecutor涓繍琛岄樆濉炵殑requests璋冪敤
            raw_response_text = await loop.run_in_executor(None, partial_blocking_post)
            
            data = json.loads(raw_response_text)
            log.info(">> G-code Script (async): %s -> Moonraker Response: %s", script, data)
            return data.get('result', '')
        except requests.exceptions.RequestException as e:
            log.error(f"Moonraker API request failed (async) for script '{script}': {e}")
            raise MoonrakerError(f"Failed to send command to Moonraker (async): {e}")
        except json.JSONDecodeError as e:
            log.error(f"Failed to decode JSON response from Moonraker (async) for script '{script}': {e}. Response text: {raw_response_text if 'raw_response_text' in locals() else 'Unknown'}")
            raise MoonrakerError(f"Invalid JSON response from Moonraker (async): {e}")

    def _blocking_post(self, url: str, script: str) -> str:
        """瀹為檯鎵ц闃诲鐨凱OST璇锋眰鐨勮緟鍔╂柟娉?""
        r = requests.post(url, json={"script": script}, timeout=180)
        r.raise_for_status()
        return r.text

    def _parse_pump_service_logs(self, logs: str):
        """浠嶱umpService鏃ュ織涓В鏋怰PM鍜屽湀鏁?""
        if not isinstance(logs, str):
            log.warning(f"鏃犳硶瑙ｆ瀽鏃ュ織锛氭湡鏈涘瓧绗︿覆锛屼絾寰楀埌 {type(logs)}")
            return None, None
            
        log.debug(f"灏濊瘯瑙ｆ瀽PumpService鏃ュ織: {logs[:200]}...") # 鎵撳嵃鍓?00涓瓧绗︾敤浜庤皟璇?
        rpm_match = self.rpm_regex.search(logs)
        revolutions_match = self.revolutions_regex.search(logs)
        
        log.debug(f"RPM姝ｅ垯琛ㄨ揪寮忓尮閰嶇粨鏋? {rpm_match}")
        log.debug(f"鍦堟暟姝ｅ垯琛ㄨ揪寮忓尮閰嶇粨鏋? {revolutions_match}")

        rpm = float(rpm_match.group(1)) if rpm_match else None
        revolutions = float(revolutions_match.group(1)) if revolutions_match else None

        log.info(f"浠庢棩蹇椾腑瑙ｆ瀽寰楀埌: RPM={rpm}, Revolutions={revolutions}")

        if rpm and revolutions:
            log.info(f"浠庢棩蹇椾腑瑙ｆ瀽鎴愬姛: RPM={rpm}, Revolutions={revolutions}")
        else:
            # 璁板綍鏇磋缁嗙殑淇℃伅锛屽府鍔╄瘑鍒ā寮忎笉鍖归厤鐨勫師鍥?            log.warning(f"鏈兘浠庢棩蹇椾腑瀹屾暣瑙ｆ瀽RPM鍜孯evolutions銆?)
            # 灏濊瘯鎵惧嚭鍙兘鍖呭惈鍏抽敭淇℃伅鐨勮
            rpm_lines = [line for line in logs.split('\n') if 'rpm' in line.lower() or '杞€? in line]
            rev_lines = [line for line in logs.split('\n') if '鍦? in line or '杞姩' in line]
            if rpm_lines:
                log.warning(f"鍙兘鍖呭惈RPM淇℃伅鐨勮: {rpm_lines}")
            if rev_lines:
                log.warning(f"鍙兘鍖呭惈鍦堟暟淇℃伅鐨勮: {rev_lines}")
                
        return rpm, revolutions

    def _estimate_parameters_fallback(self, volume_ml: float, speed: str = "normal") -> Dict[str, Any]:
        """浼扮畻娉靛弬鏁帮紙鍥為€€鏂规硶锛?
        褰撴棤娉曚粠WebSocket鑾峰彇绮剧‘鍙傛暟鏃讹紝浣跨敤姝ゆ柟娉曡繘琛屼及绠椼€?
        Args:
            volume_ml: 鐩爣浣撶Н(ml)
            speed: 閫熷害绫诲瀷锛?slow", "normal", 鎴?"fast"

        Returns:
            Dict: 鍖呭惈浼扮畻鐨剅pm銆乺evolutions鍜宔stimated_duration
        """
        # 纭繚閫熷害绫诲瀷鏈夋晥
        speed_key = speed.lower() if speed.lower() in self.fallback_calibration else "normal"
        
        # 鑾峰彇瀵瑰簲閫熷害鐨凴PM鍜宮l_per_rev
        rpm = self.fallback_calibration[speed_key]['rpm']
        ml_per_rev = self.fallback_calibration[speed_key]['ml_per_rev']
        
        # 浼扮畻鍦堟暟
        revolutions = volume_ml / ml_per_rev if ml_per_rev > 0 else 0
        
        # 浼扮畻鏃堕暱锛堢锛?        estimated_duration = (revolutions / rpm) * 60 if rpm > 0 else 0
        
        result = {
            "rpm": rpm,
            "revolutions": revolutions,
            "estimated_duration": estimated_duration
        }
        
        log.info(f"浼扮畻鍙傛暟: 浣撶Н={volume_ml}ml, 閫熷害={speed}, "
                f"浼扮畻RPM={rpm}, 浼扮畻鍦堟暟={revolutions:.2f}, "
                f"浼扮畻鏃堕暱={estimated_duration:.2f}绉?(鍥為€€鏂规硶)")
        
        return result

    # --- public API ---
    async def dispense_auto(self, volume_ml: float, speed: str = "normal", direction: int = 1) -> Dict[str, Any]:
        """鑷姩娉甸€佹寚瀹氫綋绉?
        鍙戦€佽嚜鍔ㄦ车閫佸懡浠わ紝骞朵粠WebSocket鐩戝惉鍣ㄨ幏鍙栫簿纭弬鏁般€?        濡傛灉鏃犳硶鑾峰彇绮剧‘鍙傛暟锛屽垯鍥為€€鍒颁及绠楁柟娉曘€?
        Args:
            volume_ml: 鐩爣浣撶Н(ml)
            speed: 閫熷害绫诲瀷锛?slow", "normal", 鎴?"fast"
            direction: 鏂瑰悜锛?琛ㄧず椤烘椂閽堬紝0琛ㄧず閫嗘椂閽?
        Returns:
            Dict: 鍖呭惈success銆乺pm銆乺evolutions鍜宔stimated_duration鐨勫瓧鍏?        """
        # 璋冩暣鍙傛暟鏍煎紡
        parts = [f"V={volume_ml}"]
        for_arg = "N"
        if speed and speed.lower() in ["slow", "normal", "fast"]:
            for_arg = speed[0].upper()
        parts.append(f"FOR={for_arg}")
        
        if direction is not None:
            dir_value = 0 if direction == 0 else 1  # 纭繚鏂瑰悜鍊间负0鎴?
            parts.append(f"DIR={dir_value}")
        
        # 鐢熸垚浠诲姟ID
        task_id = str(uuid.uuid4())
        log.info(f"鍒涘缓娉甸€佷换鍔?{task_id}: volume={volume_ml}ml, speed={speed}, direction={direction}")
            
        # 鏋勫缓G-code鍛戒护
        script = "DISPENSE_FLUID_AUTO " + " ".join(parts)
        
        # 鎻愬墠浣跨敤棰勪及鍙傛暟寤虹珛鍩烘湰淇℃伅
        # 鍗充娇娌℃湁鑾峰彇鍒扮‘鍒囧弬鏁颁篃鍙互杩斿洖鍚堢悊浼拌
        fallback_params = self._estimate_parameters_fallback(volume_ml, speed)
        
        # 鍙戦€佸懡浠ゅ拰绛夊緟WebSocket鍙傛暟骞惰杩涜
        # 浣跨敤asyncio.gather鍚屾椂鍚姩涓や釜浠诲姟
        
        # 鍛戒护鍙戦€佷换鍔?- 璁剧疆瓒呮椂
        async def send_command_with_timeout():
            try:
                # 涓篲send_async璁剧疆瓒呮椂锛岄伩鍏嶆棤闄愮瓑寰?                return await asyncio.wait_for(
                    self._send_async(script),
                    timeout=2.0  # 2绉掕秴鏃?- 鍙负鑾峰彇鍛戒护纭锛岄潪甯稿揩
                )
            except asyncio.TimeoutError:
                log.warning(f"浠诲姟 {task_id} G-code鍛戒护鍙戦€佽秴鏃讹紝浣嗗懡浠ゅ彲鑳藉凡鍙戦€併€傜户缁墽琛?..")
                return "Command sent, but response timed out"
            
        # WebSocket鍙傛暟鑾峰彇浠诲姟 - 璁剧疆瓒呮椂
        async def get_ws_params_with_timeout():
            if not self.listener:
                log.info(f"浠诲姟 {task_id} 鏈彁渚沇ebSocket鐩戝惉鍣紝杩斿洖None")
                return None
                
            try:
                # 绛夊緟WebSocket鍙傛暟锛屾渶澶氱瓑5绉?                return await asyncio.wait_for(
                    self.listener.wait_for_parsed_data(task_id),
                    timeout=5.0  # 5绉掕秴鏃讹紝濡傛灉5绉掑唴鏈敹鍒板弬鏁帮紝浣跨敤鍥為€€鍊?                )
            except asyncio.TimeoutError:
                log.warning(f"浠诲姟 {task_id} 绛夊緟WebSocket鍙傛暟瓒呮椂锛屽皢浣跨敤鍥為€€浼扮畻")
                return None
        
        # 骞惰鎵ц鍛戒护鍙戦€佸拰鍙傛暟绛夊緟
        send_task = asyncio.create_task(send_command_with_timeout())
        params_task = asyncio.create_task(get_ws_params_with_timeout())
        
        # 绛夊緟鍏朵腑浠讳綍涓€涓换鍔″畬鎴愬嵆鍙户缁?        done, pending = await asyncio.wait(
            [send_task, params_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # 妫€鏌ュ弬鏁颁换鍔℃槸鍚﹀畬鎴?        ws_pump_params = None
        if params_task in done:
            ws_pump_params = params_task.result()
            if ws_pump_params:
                log.info(f"浠诲姟 {task_id} 鎴愬姛浠嶹ebSocket鑾峰彇鍙傛暟: {ws_pump_params}")
                # 鍗充娇鍛戒护鍙戦€佷换鍔℃湭瀹屾垚锛屼篃鍙互杩斿洖鍙傛暟缁撴灉
                if send_task in pending:
                    # 鍙栨秷鍛戒护鍙戦€佺瓑寰呬絾涓嶄腑鏂懡浠ゆ湰韬紝鍛戒护宸茬粡鍙戦€?                    send_task.cancel()
                    
                return {
                        "success": True,
                        "rpm": ws_pump_params["rpm"],
                        "revolutions": ws_pump_params["revolutions"],
                        "estimated_duration": ws_pump_params["estimated_duration"],
                        "source": "websocket",
                    "raw_response": "WebSocket parameters received before command completion"
                }
        
        # 濡傛灉WebSocket鍙傛暟鏈幏鍙栨垨鏈畬鎴愶紝绛夊緟鍛戒护鍙戦€佸畬鎴?        # 浣嗚缃€昏秴鏃讹紝閬垮厤鏃犻檺绛夊緟
        try:
            raw_response = None
            if send_task in done:
                raw_response = send_task.result()
            else:
                # 绛夊緟鍛戒护鍙戦€佸畬鎴愶紝浣嗚缃緝鐭秴鏃?                try:
                    raw_response = await asyncio.wait_for(send_task, timeout=1.0)
                except asyncio.TimeoutError:
                    log.warning(f"浠诲姟 {task_id} 鍛戒护鍙戦€佺‘璁よ秴鏃讹紝浣嗗懡浠ゅ彲鑳藉凡鍙戦€?)
                    raw_response = "Command sent, confirmation timed out"
                    
            # 缁х画绛夊緟鍙傛暟浠诲姟涓€灏忔鏃堕棿锛屽鏋滆繕鏈畬鎴?            if params_task in pending:
                try:
                    ws_pump_params = await asyncio.wait_for(params_task, timeout=2.0)
                    if ws_pump_params:
                        log.info(f"浠诲姟 {task_id} 鍦ㄥ懡浠ゅ畬鎴愬悗鑾峰彇鍒癢ebSocket鍙傛暟")
                except asyncio.TimeoutError:
                    # 濡傛灉鍙傛暟浠诲姟瓒呮椂锛屽彇娑堝畠
                    params_task.cancel()
                    log.warning(f"浠诲姟 {task_id} 鍙傛暟鑾峰彇鏈€缁堣秴鏃讹紝灏嗕娇鐢ㄥ洖閫€浼扮畻")
        except Exception as e:
            log.error(f"浠诲姟 {task_id} 绛夊緟鍛戒护鎴栧弬鏁版椂鍑洪敊: {e}", exc_info=True)
            # 纭繚鍙栨秷鎵€鏈夋湭瀹屾垚鐨勪换鍔?            for task in pending:
                task.cancel()
        
        # 濡傛灉宸茶幏鍙朩ebSocket鍙傛暟锛岃繑鍥炲畠
        if ws_pump_params:
            return {
                "success": True,
                "rpm": ws_pump_params["rpm"],
                "revolutions": ws_pump_params["revolutions"],
                "estimated_duration": ws_pump_params["estimated_duration"],
                "source": "websocket",
                "raw_response": str(raw_response) if raw_response else "Unknown response"
            }
            
        # 濡傛灉娌℃湁WebSocket鍙傛暟锛屽皾璇曚粠鍝嶅簲鏃ュ織瑙ｆ瀽
        if raw_response:
            rpm_from_response, revolutions_from_response = self._parse_pump_service_logs(str(raw_response))
            if rpm_from_response is not None and revolutions_from_response is not None:
                log.info(f"浠诲姟 {task_id} 浠庡搷搴旀棩蹇椾腑瑙ｆ瀽寰楀埌: RPM={rpm_from_response}, 鍦堟暟={revolutions_from_response}")
                estimated_duration = (revolutions_from_response / rpm_from_response) * 60 if rpm_from_response > 0 else 0
                return {
                    "success": True,
                    "rpm": rpm_from_response,
                    "revolutions": revolutions_from_response,
                    "estimated_duration": estimated_duration,
                    "source": "response_log",
                    "raw_response": str(raw_response)
                }
        
        # 濡傛灉閮藉け璐ヤ簡锛屼娇鐢ㄥ洖閫€浼扮畻
        log.warning(f"浠诲姟 {task_id} 鏃犳硶鑾峰彇绮剧‘鍙傛暟锛屼娇鐢ㄥ洖閫€浼扮畻")
        return {
                "success": True,
                "rpm": fallback_params["rpm"],
                "revolutions": fallback_params["revolutions"],
                "estimated_duration": fallback_params["estimated_duration"],
                "source": "fallback",
            "raw_response": str(raw_response) if raw_response else "Unknown response"
            }

    async def dispense_speed(self, volume_ml: float, speed_rpm: float, direction: int = 1) -> Dict[str, Any]:
        """浣跨敤鍥哄畾閫熷害娉甸€侊紙瀹氭椂娉甸€佺殑搴曞眰鏂规硶锛?
        Args:
            volume_ml: 鐩爣浣撶Н(ml)锛岀敤浜庝及绠楀湀鏁?            speed_rpm: 杞€?RPM)
            direction: 鏂瑰悜锛?琛ㄧず椤烘椂閽堬紝0琛ㄧず閫嗘椂閽?
        Returns:
            Dict: 鍖呭惈success銆乺pm銆乺evolutions鍜宔stimated_duration鐨勫瓧鍏?        """
        # 璋冩暣鍙傛暟鏍煎紡
        parts = [f"V={volume_ml}", f"S={speed_rpm}"]
        
        if direction is not None:
            dir_value = 0 if direction == 0 else 1  # 纭繚鏂瑰悜鍊间负0鎴?
            parts.append(f"DIR={dir_value}")
        
        # 鐢熸垚浠诲姟ID
        task_id = str(uuid.uuid4())
        log.info(f"鍒涘缓瀹氶€熸车閫佷换鍔?{task_id}: volume={volume_ml}ml, speed_rpm={speed_rpm}, direction={direction}")
            
        # 鏋勫缓G-code鍛戒护
        script = "DISPENSE_FLUID_SPEED " + " ".join(parts)
        
        # 棣栧厛鍚姩鍛戒护鍙戦€?        send_task = asyncio.create_task(self._send_async(script))
            
        # 鍚屾椂锛屽紑濮嬬瓑寰匴ebSocket鐨勫弬鏁?(涓昏鏄湀鏁?
        ws_pump_params = None
        if self.listener:
            log.info(f"浠诲姟 {task_id} 寮€濮嬬瓑寰匴ebSocket娉靛弬鏁?(涓庡懡浠ゅ彂閫佸苟琛?...")
            ws_pump_params = await self.listener.wait_for_parsed_data(task_id, timeout=7.0) 
            if ws_pump_params and ws_pump_params.get("revolutions"):
                log.info(f"浠嶹ebSocket鑾峰彇鍒版车鍙傛暟: {ws_pump_params}")
            else:
                log.warning(f"鏃犳硶浠嶹ebSocket鑾峰彇浠诲姟 {task_id} 鐨勬车鍙傛暟(鍦堟暟)锛屽皢渚濊禆鍚庣画澶勭悊銆?)
        else:
            log.info("鏈彁渚沇ebSocket鐩戝惉鍣紝灏嗕緷璧栧悗缁鐞嗐€?)
        
        # 绛夊緟鍛戒护鍙戦€佸畬鎴?        try:
            raw_response = await send_task
            log.info(f"浠诲姟 {task_id} G-code鍛戒护鍙戦€佸畬鎴愶紝Moonraker鍝嶅簲: {str(raw_response)[:200]}...")
        except Exception as e:
            log.error(f"浠诲姟 {task_id} G-code鍛戒护鍙戦€佸け璐? {e}", exc_info=True)
            return {"success": False, "error": str(e), "source": "send_error"}

        # 鍙傛暟鑾峰彇鍜岀粍瑁呴€昏緫
        try:
            if ws_pump_params and ws_pump_params.get("revolutions"):
                revolutions = ws_pump_params["revolutions"]
                estimated_duration = (revolutions / speed_rpm) * 60 if speed_rpm > 0 else 0
                return {
                    "success": True,
                    "rpm": speed_rpm, 
                    "revolutions": revolutions,
                    "estimated_duration": estimated_duration,
                    "source": "websocket",
                    "raw_response": str(raw_response)
                }
            
            # 濡傛灉WebSocket澶辫触锛屽皾璇曚粠鍝嶅簲鏃ュ織瑙ｆ瀽鍦堟暟
            _, revolutions_from_response = self._parse_pump_service_logs(str(raw_response))
            if revolutions_from_response is not None:
                log.info(f"浠庡搷搴旀棩蹇椾腑鐩存帴瑙ｆ瀽寰楀埌: 鍦堟暟={revolutions_from_response}")
                estimated_duration = (revolutions_from_response / speed_rpm) * 60 if speed_rpm > 0 else 0
                return {
                    "success": True,
                    "rpm": speed_rpm,
                    "revolutions": revolutions_from_response,
                    "estimated_duration": estimated_duration,
                    "source": "response_log",
                    "raw_response": str(raw_response)
                }
            
            # 鍥為€€浼扮畻
            ml_per_rev = 0.08 # 榛樿鍊?            revolutions_fallback = volume_ml / ml_per_rev if ml_per_rev > 0 else 0
            estimated_duration_fallback = (revolutions_fallback / speed_rpm) * 60 if speed_rpm > 0 else 0
            log.info(f"浼扮畻鍙傛暟: 浣撶Н={volume_ml}ml, RPM={speed_rpm}, "
                    f"浼扮畻鍦堟暟={revolutions_fallback:.2f}, 浼扮畻鏃堕暱={estimated_duration_fallback:.2f}绉?(鍩烘湰浼扮畻)")
            return {
                "success": True,
                "rpm": speed_rpm,
                "revolutions": revolutions_fallback,
                "estimated_duration": estimated_duration_fallback,
                "source": "estimate",
                "raw_response": str(raw_response)
            }
            
        except Exception as e:
            log.error(f"澶勭悊浠诲姟 {task_id} 鐨勫畾閫熸车閫佸弬鏁版椂鍑洪敊: {e}", exc_info=True)
            return {"success": False, "error": str(e), "source": "parameter_error", "raw_response": str(raw_response)}

    async def emergency_stop(self) -> Dict[str, Any]:
        """绱ф€ュ仠姝㈡墍鏈夋车 (寮傛)

        Returns:
            Dict: 鍖呭惈success鐨勫瓧鍏?        """
        try:
            script = "STOP_PUMP"
            response = await self._send_async(script) # 鏀逛负璋冪敤寮傛鐗堟湰
            return {
                "success": True,
                "raw_response": str(response)
            }
        except Exception as e:
            log.error(f"鎵цemergency_stop鏃跺嚭閿? {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }
