# F8 step 3: Chat protections replayed through voice_session(channel="chat")

## Gaps found early (step 2), to close in step 3

- G1 `PrivateWord`: without an understander, a model that already knows the caller's name (system
  prompt, app history) can write it into an answer to a general question; voice saves it shared.
  `VoicePrivateWord` is only in `RuleSet.understood()` and `CallState.remembers_told` is off without
  a classifier. Chat's `PrivateWord` caught this.
