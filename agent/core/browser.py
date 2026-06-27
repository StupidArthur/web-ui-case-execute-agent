"""Playwright 浏览器工具面。"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime
from typing import Any

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from agent.core.grounding import GroundingError
from agent.core.models import GroundingResult
from agent.core.page_state import serialize_page_state


class ActionError(Exception):
    """动作执行异常。"""

    pass


class Browser:
    """封装 Playwright 页面操作。"""

    def __init__(self, page: Page, trace_dir: str | None = None):
        self.page = page
        self.trace_dir = trace_dir

    async def get_page_state(self) -> str:
        """拍 AX 快照并返回 YAML 风格文本。

        Playwright Python 没有 page.accessibility，使用 aria_snapshot() 获取 ARIA 树文本。
        """
        return await self.page.aria_snapshot()

    async def perform_action(
        self,
        action_type: str,
        gr: GroundingResult | None,
        value: str | None,
    ) -> None:
        """规则派发执行动作。"""
        if action_type in {"click", "fill", "check", "upload", "download", "keypress"}:
            if gr is None or gr.locator is None:
                raise GroundingError(f"动作 {action_type} 需要 grounding 结果")
            loc = await self._resolve_locator(gr)

            if action_type == "click":
                await loc.click()
            elif action_type == "fill":
                await loc.fill(value or "")
            elif action_type == "check":
                await loc.check()
            elif action_type == "keypress":
                await loc.press(value or "Enter")
            elif action_type == "upload":
                if not value or not os.path.exists(value):
                    raise ActionError(f"上传文件不存在: {value}")
                await loc.set_input_files(value)
            elif action_type == "download":
                # download 先按 click 触发下载处理
                async with self.page.expect_download() as download_info:
                    await loc.click()
                download = await download_info.value
                if self.trace_dir:
                    await download.save_as(os.path.join(self.trace_dir, download.suggested_filename))

        elif action_type == "scroll":
            await self.page.evaluate("window.scrollBy(0, window.innerHeight / 2)")

        elif action_type == "wait":
            # 用例明确写明等待时长（value=秒数）时必须等够；否则走自适应等待
            if value:
                try:
                    seconds = float(value)
                except (TypeError, ValueError):
                    seconds = 0.0
                await self.wait_explicit(seconds)
            else:
                await self.wait_normal(timeout_s=3)

        else:
            raise ActionError(f"未知动作类型: {action_type}")

    async def _resolve_locator(self, gr: GroundingResult) -> Any:
        """将 GroundingResult 解析为 Playwright Locator。"""
        role = gr.locator.role
        name = gr.locator.name
        # name 为空时，使用 get_by_role 不带 name 参数
        if name:
            loc = self.page.get_by_role(role, name=name)
        else:
            loc = self.page.get_by_role(role)
        count = await loc.count()
        if count == 0:
            raise GroundingError(f"get_by_role 未匹配: {gr.locator}")
        if count == 1:
            return loc
        # 多匹配：用 ref 消歧（1-based nth）
        idx = gr.ref - 1
        if idx < 0 or idx >= count:
            raise GroundingError(f"ref {gr.ref} 超出范围 (count={count})")
        return loc.nth(idx)

    async def wait_stable(self, timeout_s: float = 4.0) -> None:
        """动作后的阶梯式自适应等待：快页面早退，慢页面降低轮询频率，永不抛异常。

        - 轮询间隔阶梯递增：200ms→500ms→1s，封顶 1s。状态在变时逐步拉长间隔，
          避免对慢页面频繁打扰；状态稳定后立即返回。
        - 稳定判定：URL 与 AX 哈希连续 2 轮一致。
        - 超时即视为"等够了"返回（不抛），交给 verify 判定状态。
        """
        intervals = [0.2, 0.5, 1.0]  # 阶梯，最后一档循环
        deadline = time.time() + timeout_s
        last_url = None
        last_hash = ""
        stable_count = 0
        i = 0
        first_sample = True

        while time.time() < deadline:
            try:
                url = self.page.url
                ax_text = await self.get_page_state()
            except Exception:
                url = ""
                ax_text = ""
            current_hash = hashlib.md5(ax_text.encode("utf-8")).hexdigest()

            if first_sample:
                first_sample = False
            elif url == last_url and current_hash == last_hash:
                stable_count += 1
                if stable_count >= 2:
                    return
            else:
                stable_count = 0

            last_url = url
            last_hash = current_hash
            interval = intervals[min(i, len(intervals) - 1)]
            i += 1
            await self.page.wait_for_timeout(int(interval * 1000))

    async def wait_for_navigation_settle(self, timeout_s: float = 30.0) -> None:
        """导航/重定向后阶梯式等待落地，防过早返回，永不抛异常。

        - 轮询间隔阶梯递增：500ms→1s→2s，封顶 2s。快页面早退，慢页面不频繁打扰。
          每次观测到状态变化时重置阶梯，让变化后的确认用短间隔快速完成。
        - 稳定判定：URL 与 AX 哈希连续 2 轮一致。
        - 防过早返回（核心）：以 **URL 是否变化** 判断重定向是否已发生。
          · URL 已变化（重定向已发生）→ 连续 2 轮一致即返回；
          · URL 自始未变（疑似重定向待发生，如登录页 3~5s 后才跳 /login）
            → 必须等过 MIN_NO_REDIRECT_DWELL 且连续 2 轮一致才返回，
              避免在中间页（邀请码页）渲染稳定后、重定向发生前误判稳定。
          注：不能用 AX 哈希变化判断"重定向已发生"——中间页自身渲染也会变哈希。
        - 超时即视为"等够了"返回（不抛），交给 verify 判定。
        """
        intervals = [0.5, 1.0, 2.0]  # 阶梯，最后一档循环
        MIN_NO_REDIRECT_DWELL = 5.0  # URL 未变化时至少观察这么久（覆盖 3~5s 重定向窗口）
        deadline = time.time() + timeout_s
        start_time = time.time()
        first_url = None
        last_url = None
        last_hash = ""
        stable_count = 0
        url_changed = False
        i = 0
        first_sample = True

        while time.time() < deadline:
            try:
                url = self.page.url
                ax_text = await self.get_page_state()
            except Exception:
                url = ""
                ax_text = ""
            current_hash = hashlib.md5(ax_text.encode("utf-8")).hexdigest()

            if first_sample:
                first_sample = False
                first_url = url
            elif url != last_url or current_hash != last_hash:
                # 状态在变：重置稳定计数与阶梯间隔，变化后用短间隔快速确认
                stable_count = 0
                i = 0
                if url != first_url:
                    url_changed = True
            else:
                stable_count += 1
                if url_changed:
                    if stable_count >= 2:
                        return
                else:
                    # URL 自始未变：等过重定向窗口后才允许判稳
                    if (time.time() - start_time) >= MIN_NO_REDIRECT_DWELL and stable_count >= 2:
                        return

            last_url = url
            last_hash = current_hash
            interval = intervals[min(i, len(intervals) - 1)]
            i += 1
            await self.page.wait_for_timeout(int(interval * 1000))
        # 超时也返回，不抛

    async def wait_normal(self, timeout_s: float = 8.0) -> None:
        """普通等待：页面跳转/异步加载。"""
        await self.wait_stable(timeout_s=timeout_s)

    async def wait_explicit(self, seconds: float) -> None:
        """显式等待：用例明确要求等够 N 秒，必须等满，不早退、不熔断。"""
        if seconds <= 0:
            return
        await self.page.wait_for_timeout(int(seconds * 1000))

    async def wait_active(self, timeout_s: float = 60.0) -> None:
        """主动等待：AI 处理/长任务。检测流式停止（连续 3 次无变化）。"""
        deadline = time.time() + timeout_s
        last_hash = ""
        stable_count = 0
        while time.time() < deadline:
            try:
                ax_text = await self.get_page_state()
            except Exception:
                ax_text = ""
            current_hash = hashlib.md5(ax_text.encode("utf-8")).hexdigest()
            if current_hash == last_hash:
                stable_count += 1
            else:
                stable_count = 0
            if stable_count >= 3:
                return
            last_hash = current_hash
            await self.page.wait_for_timeout(1000)

    async def detect_loop(self) -> bool:
        """DOM 连续 3 次无变化返回 True（标记用，不中断）。"""
        hashes: list[str] = []
        for _ in range(4):
            try:
                ax_text = await self.get_page_state()
            except Exception:
                ax_text = ""
            hashes.append(hashlib.md5(ax_text.encode("utf-8")).hexdigest())
            await self.page.wait_for_timeout(500)

        # 最近 3 次是否相同
        return len(set(hashes[-3:])) == 1 if len(hashes) >= 3 else False

    async def scroll_chat_to_bottom_if_exists(self) -> None:
        """若存在 class=chat-history 元素，滚动到底。"""
        try:
            chat_history = self.page.locator(".chat-history")
            count = await chat_history.count()
            if count > 0:
                await chat_history.last.evaluate("el => el.scrollTop = el.scrollHeight")
        except Exception:
            pass

    async def screenshot(self) -> str:
        """截图并返回保存路径。"""
        filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
        if self.trace_dir:
            os.makedirs(self.trace_dir, exist_ok=True)
            path = os.path.join(self.trace_dir, filename)
        else:
            path = os.path.join(os.getcwd(), filename)
        await self.page.screenshot(path=path, full_page=True)
        return path
