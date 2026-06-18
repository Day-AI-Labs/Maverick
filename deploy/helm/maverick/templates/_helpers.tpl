{{- define "maverick.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "maverick.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "maverick.labels" -}}
app.kubernetes.io/name: {{ include "maverick.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end -}}

{{- define "maverick.selectorLabels" -}}
app.kubernetes.io/name: {{ include "maverick.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "maverick.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) -}}
{{- end -}}

{{- define "maverick.secretName" -}}
{{- default (printf "%s-secrets" (include "maverick.fullname" .)) .Values.secret.name -}}
{{- end -}}

{{/* Guard: SQLite cannot run multiple writers. */}}
{{- define "maverick.validate" -}}
{{- if and (gt (int .Values.replicaCount) 1) (ne .Values.worldModel.backend "postgres") -}}
{{- fail "replicaCount > 1 requires worldModel.backend=postgres (SQLite is single-writer on a RWO volume)" -}}
{{- end -}}
{{- end -}}
