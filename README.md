# GADE CUA Evolve

This repository contains a minimal provider interface for executing generated `pyautogui` actions through controlled computer providers.

## Safety

Generated `pyautogui` code can control the keyboard, mouse, windows, files, browser sessions, and other local resources exposed to the process. Treat generated actions as untrusted automation.

* Execute generated code only inside an isolated virtual machine or similarly disposable sandbox.
* Do not run generated `pyautogui` actions directly on a personal or primary host machine.
* Providers must enforce operational controls, including execution timeouts, stdout/stderr logging, action audit logs, and the minimum permissions required for the target environment.
