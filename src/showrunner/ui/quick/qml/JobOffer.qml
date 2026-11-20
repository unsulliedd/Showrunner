import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The offer of a job an earlier run left unfinished: resume it, discard it, or ask again next time. One that this
// version cannot read back can only be discarded or kept for later. Nothing resumes without a click here; Escape
// is "Ask next time".
Popup {
    id: offer

    readonly property var job: app.jobs.offer

    objectName: "jobOffer"
    anchors.centerIn: Overlay.overlay
    width: Theme.dialog_width / 2 + Theme.space_2xl * 2
    padding: Theme.space_xl
    modal: true
    focus: true
    closePolicy: Popup.NoAutoClose
    visible: job.id !== undefined

    Overlay.modal: Rectangle {
        color: Theme.ground
        opacity: Theme.dim_percent / 100  // the window stays readable behind the offer
    }

    background: Rectangle {
        radius: Theme.radius_lg
        color: Theme.panel_2
        border.width: Theme.stroke
        border.color: Theme.line_strong
    }

    contentItem: ColumnLayout {
        spacing: Theme.space_lg
        focus: true
        // Not a close policy: closing the popup would break the binding on `visible`. Escape answers the offer.
        Keys.onEscapePressed: app.jobs.later_offer()

        RowLayout {
            spacing: Theme.space_md

            Icon {
                name: "resume"
                color: Theme.change
            }

            UiText {
                Layout.fillWidth: true
                text: Strings.t("jobs.title")
                font.pixelSize: Theme.text_lg
                font.weight: Font.Bold
                Accessible.role: Accessible.Heading
            }

            UiText {
                text: offer.job.when || ""
                color: Theme.faint
                font.pixelSize: Theme.text_sm
            }
        }

        UiText {
            Layout.fillWidth: true
            text: offer.job.text || ""
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
        }

        UiText {
            Layout.fillWidth: true
            visible: offer.job.resumable === true
            text: Strings.t("jobs.safety")
            color: Theme.muted
            font.pixelSize: Theme.text_sm
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_md

            Item {
                Layout.fillWidth: true
            }

            ActionButton {
                kind: "ghost"
                text: Strings.t("jobs.later")
                onClicked: app.jobs.later_offer()
            }

            ActionButton {
                objectName: "discardJob"
                kind: "outline"
                text: Strings.t("jobs.discard")
                onClicked: app.jobs.discard_offer()
            }

            ActionButton {
                objectName: "resumeJob"
                visible: offer.job.resumable === true
                enabled: !app.jobs.running
                kind: "primary"
                iconName: "resume"
                text: Strings.t("jobs.resume")
                onClicked: app.jobs.resume_offer()
            }
        }
    }
}
