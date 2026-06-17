package dev.maverick

import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import java.net.HttpURLConnection
import java.net.URI
import java.util.concurrent.atomic.AtomicBoolean
import javax.swing.JButton
import javax.swing.JPanel
import javax.swing.JTextField
import kotlin.concurrent.thread

/**
 * Maverick Runs tool window: enter a goal id, stream its events live from
 * the local dashboard's SSE endpoint into the text area. Reconnect/backoff
 * mirrors the VS Code extension; the watch stops when the window closes or
 * Stop is pressed.
 */
class RunsToolWindowFactory : ToolWindowFactory {
    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val output = JBTextArea().apply { isEditable = false }
        val goalField = JTextField(8)
        val watch = JButton("Watch live")
        val stop = JButton("Stop")
        val stopped = AtomicBoolean(true)

        fun appendLine(line: String) =
            javax.swing.SwingUtilities.invokeLater { output.append(line + "\n") }

        watch.addActionListener {
            val goalId = goalField.text.trim().toLongOrNull() ?: return@addActionListener
            stopped.set(false)
            thread(isDaemon = true, name = "maverick-sse-$goalId") {
                var backoffMs = 1000L
                val base = System.getenv("MAVERICK_DASHBOARD_URL") ?: "http://127.0.0.1:8765"
                val token = System.getenv("MAVERICK_DASHBOARD_TOKEN")
                while (!stopped.get()) {
                    try {
                        val conn = URI("$base/api/v1/goals/$goalId/events/stream")
                            .toURL().openConnection() as HttpURLConnection
                        if (!token.isNullOrBlank()) {
                            conn.setRequestProperty("Authorization", "Bearer $token")
                        }
                        conn.inputStream.bufferedReader().useLines { lines ->
                            backoffMs = 1000L
                            lines.forEach { line ->
                                if (stopped.get()) return@forEach
                                if (line.startsWith("data:")) appendLine(line.removePrefix("data:").trim())
                            }
                        }
                    } catch (e: Exception) {
                        appendLine("[stream error: ${e.message}; retrying in ${backoffMs / 1000}s]")
                    }
                    if (!stopped.get()) {
                        Thread.sleep(backoffMs)
                        backoffMs = (backoffMs * 2).coerceAtMost(30_000L)
                    }
                }
                appendLine("[live watch stopped]")
            }
        }
        stop.addActionListener { stopped.set(true) }

        val controls = JPanel().apply { add(goalField); add(watch); add(stop) }
        val panel = JPanel(java.awt.BorderLayout()).apply {
            add(controls, java.awt.BorderLayout.NORTH)
            add(JBScrollPane(output), java.awt.BorderLayout.CENTER)
        }
        toolWindow.contentManager.addContent(
            toolWindow.contentManager.factory.createContent(panel, "", false))
    }
}
