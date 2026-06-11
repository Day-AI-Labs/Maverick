;;; maverick.el --- Drive the Maverick agent runtime from Emacs -*- lexical-binding: t; -*-

;; Copyright (C) 2027 Day AI Labs

;; Author: Day AI Labs
;; Version: 0.1.0
;; Package-Requires: ((emacs "27.1"))
;; Keywords: tools, processes
;; URL: https://github.com/Day-AI-Labs/maverick

;;; Commentary:

;; A thin, dependency-free front end over the `maverick' CLI:
;;
;;   M-x maverick-start    — prompt for a goal, run it (async, compilation buffer)
;;   M-x maverick-status   — show runtime status (+ cost)
;;   M-x maverick-monitor  — live plan-tree TUI in a term buffer
;;   M-x maverick-logs     — tail recent run logs
;;   M-x maverick-halt     — arm the killswitch (~/.maverick/HALT)
;;   M-x maverick-unhalt   — clear the killswitch
;;
;; The package shells out to the locally installed CLI; nothing here talks to
;; a network itself.  Set `maverick-cli-path' if `maverick' isn't on PATH.

;;; Code:

(defgroup maverick nil
  "Drive the Maverick agent runtime."
  :group 'tools
  :prefix "maverick-")

(defcustom maverick-cli-path "maverick"
  "Path to the maverick CLI executable."
  :type 'string
  :group 'maverick)

(defcustom maverick-default-max-dollars nil
  "When non-nil, pass --max-dollars to `maverick start'."
  :type '(choice (const :tag "Use config default" nil) number)
  :group 'maverick)

(defun maverick--command (&rest args)
  "Build a shell command string from `maverick-cli-path' and ARGS."
  (mapconcat #'shell-quote-argument
             (cons maverick-cli-path (delq nil args))
             " "))

;;;###autoload
(defun maverick-start (goal)
  "Start the Maverick swarm on GOAL (asynchronously)."
  (interactive "sGoal for Maverick: ")
  (let ((cmd (if maverick-default-max-dollars
                 (maverick--command "start" goal "--max-dollars"
                                    (number-to-string maverick-default-max-dollars))
               (maverick--command "start" goal))))
    (compilation-start cmd nil (lambda (_) "*maverick-run*"))))

;;;###autoload
(defun maverick-status ()
  "Show Maverick runtime status, including cost."
  (interactive)
  (let ((buf (get-buffer-create "*maverick-status*")))
    (with-current-buffer buf
      (read-only-mode -1)
      (erase-buffer)
      (call-process-shell-command (maverick--command "status" "--cost") nil buf)
      (special-mode))
    (pop-to-buffer buf)))

;;;###autoload
(defun maverick-monitor ()
  "Open the live plan-tree monitor in a term buffer."
  (interactive)
  (require 'term)
  (let ((buf (term-ansi-make-term "*maverick-monitor*" maverick-cli-path nil "monitor")))
    (with-current-buffer buf (term-char-mode))
    (pop-to-buffer buf)))

;;;###autoload
(defun maverick-logs ()
  "Show recent Maverick run logs."
  (interactive)
  (compilation-start (maverick--command "logs") nil (lambda (_) "*maverick-logs*")))

;;;###autoload
(defun maverick-halt ()
  "Arm the Maverick killswitch (aborts all running goals)."
  (interactive)
  (when (yes-or-no-p "Arm the killswitch and abort ALL running goals? ")
    (shell-command (maverick--command "halt"))
    (message "Maverick killswitch armed.")))

;;;###autoload
(defun maverick-unhalt ()
  "Clear the Maverick killswitch."
  (interactive)
  (shell-command (maverick--command "unhalt"))
  (message "Maverick killswitch cleared."))

(provide 'maverick)

;;; maverick.el ends here
