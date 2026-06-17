"""Thread-safe queue bridging the mitmproxy thread and the game_loop thread."""
import queue
import threading

state_queue: queue.Queue = queue.Queue(maxsize=100)

# Set by addon when a StartGameResp is observed. Cleared by game_loop after it
# resets the agent's conversation. Ensures the AI never carries over context
# from a previous game even if round-number detection misfires.
new_game_event: threading.Event = threading.Event()

# Set by addon when a BattleResult or SettleResult is observed — the canonical
# "round ended" signal. Cleared by game_loop, which then resets the card
# signature so the NEXT GameStatus is guaranteed to fire the AI even if the
# user's hand happens to match the previous round's signature.
round_ended_event: threading.Event = threading.Event()
