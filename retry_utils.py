"""
Décorateur de retry/backoff partagé pour tous les appels à l'API OpenAI du
projet (content_planner.py, course_planner.py, plan_chat.py).

Sans ça, une erreur transitoire (rate limit 429, timeout réseau, erreur 500
ponctuelle côté OpenAI) fait échouer tout un batch de plusieurs modules à
mi-parcours — frustrant sur un cours de 18 modules quand l'échec arrive après
15 minutes et 15 appels déjà réussis (et déjà payés).

5 tentatives, backoff exponentiel (2s, 4s, 8s, 16s, 30s max) : suffisant pour
absorber un rate-limit ponctuel ou une coupure réseau de quelques secondes,
sans faire attendre indéfiniment sur une erreur qui ne se résoudra pas seule
(auquel cas l'exception d'origine remonte normalement après la 5e tentative).
"""
from openai import RateLimitError, APIConnectionError, APITimeoutError, InternalServerError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import logging

logger = logging.getLogger(__name__)

openai_retry = retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
