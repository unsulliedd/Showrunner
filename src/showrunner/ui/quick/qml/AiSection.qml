import QtQuick
import QtQuick.Layouts
import Showrunner

// AI models: the backend and whether its server answers, and the model that translates and re-splits wherever a
// place chooses none, picked from the ones installed. The server is asked again when the section opens.
SettingsPage {
    id: page

    readonly property var ai: app.settings.ai

    title: Strings.t("prefs.section.ai")
    lead: Strings.t("prefs.ai.lead")

    actions: [
        ActionButton {
            objectName: "aiCheck"
            kind: "ghost"
            iconName: "resume"
            text: Strings.t("prefs.ai.check")
            onClicked: app.settings.check_ai()
        }
    ]

    SettingLabel {
        text: Strings.t("prefs.ai.backend")
        note: page.ai.backend
    }

    Hint {
        objectName: "aiState"
        text: page.ai.state
    }

    SettingLabel {
        text: Strings.t("prefs.ai.model")
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.space_md

        UiText {
            objectName: "aiModel"
            Layout.fillWidth: true
            text: page.ai.model
            elide: Text.ElideRight
        }

        ActionButton {
            id: pick

            objectName: "aiModelPick"
            kind: "ghost"
            iconName: "down"
            text: Strings.t("prefs.ai.model.pick")
            enabled: page.ai.models.length > 0
            onClicked: models.popup(pick, 0, pick.height)
        }

        ActionMenu {
            id: models

            actions: page.ai.models
            onPicked: key => Qt.callLater(() => app.settings.set_ai_model(key))
        }
    }

    Hint {
        text: page.ai.empty
        tone: "change"
    }
}
