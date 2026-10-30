"""
Voice assistant layer (17 Nov 2026): speech -> text -> AI (with what the camera sees + a personality)
-> {speech, commands} JSON -> chipmunk voice on the speaker + robot actions. Every part degrades
gracefully and reports failures out loud through alerts.Alerts.

Design and every constant: docs/assistant.md
"""
