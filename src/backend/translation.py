# -*- coding: utf-8 -*-
#  Copyright (C) 2026 FjiNeko
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.


import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

# --- ChatGPT 客户端初始化 ---
api_key = os.getenv("deepseek_api_key", ""),
Ai_Client = None
if not api_key:
    logger.error("ChatGPT environment variable is not set. ChatGPT translation will not work.")
else:
    try:
        Ai_Client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("deepseek_base_url", ""),
        )
        logger.info("ChatGPT client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize ChatGPT client: {e}", exc_info=True)

TRANSLATION_SYSTEM_PROMPT = """
You are a highly professional and precise translator specializing in official announcements and technical texts.
Your only task is to translate the user-provided text into the specified target language.
Adhere strictly to the following rules:
1.  Translate accurately and naturally, maintaining the original meaning, tone, and style.
2.  Do NOT add any introductions, conclusions, explanations, comments, or extra conversational text.
3.  Do NOT use any markdown formatting (like ````text```, **, _, etc.) unless explicitly present in the original text and necessary for direct translation.
4.  Output ONLY the translated text, nothing else.
5.  Maintain a formal, neutral, and objective tone suitable for official communications.
"""

LANGUAGE_MAP = {
    "en-us": "English (United States)",
    "zh-tw": "Traditional Chinese (Taiwan)",
    "zh-hk": "Traditional Chinese (Hong Kong)",
}

def translate_with_chatgpt(text: str, target_language_code: str) -> str:
    """
    使用 ChatGPT API 将文本翻译成指定语言，并带有固定角色。
    """
    if not Ai_Client:
        logger.warning("ChatGPT client is not initialized. Skipping translation.")
        return text
    if not text or not text.strip():
        return ""

    target_language_name = LANGUAGE_MAP.get(target_language_code, target_language_code)

    try:
        chat_completion = Ai_Client.chat.completions.create(
            messages=[
                {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
                {"role": "user", "content": f"Translate the following text to {target_language_name}:\n\n{text}"}
            ],
            model="gpt-5.1",
            temperature=0.1,
            max_tokens=4000
        )
        
        translated_text = chat_completion.choices[0].message.content
        clean_text = translated_text.strip()
        # ... (清理逻辑与之前相同) ...
        if clean_text.startswith('"') and clean_text.endswith('"'):
            clean_text = clean_text[1:-1]
        if clean_text.startswith("'") and clean_text.endswith("'"):
            clean_text = clean_text[1:-1]
        if clean_text.startswith("```") and clean_text.endswith("```"):
            clean_text = clean_text[3:-3].strip()
            
        return clean_text
        
    except Exception as e:
        logger.error(f"ChatGPT API translation failed for text (first 50 chars): '{text[:50]}...' "
                     f"to target '{target_language_code}': {e}", exc_info=True)
        return text

