const Streamlit = {
    _v2: false,
    _customSendDataHandler: undefined,
    init() {
        sendMessageToStreamlit('streamlit:componentReady', { apiVersion: 1 });
    },
    enableV2(handler) {
        this._v2 = true;
        this._customSendDataHandler = handler;
    },
    setFrameHeight(height) {
        if (!this._v2) {
            sendMessageToStreamlit('streamlit:setFrameHeight', { height: height });
        }
    },
    sendData(data) {
        if (this._v2) {
            const event = data.event;
            const triggerData = Object.fromEntries(Object.entries(data).filter(([k, v]) => k !== 'event'));
            this._customSendDataHandler(event, triggerData);
        } else {
            sendMessageToStreamlit('streamlit:setComponentValue', { value: data, dataType: 'json' });
        }
    },
};

function sendMessageToStreamlit(type, data) {
    if (window.top) {
        window.top.postMessage(Object.assign({ type: type, isStreamlitMessage: true }, data), '*');
    }
}

export { Streamlit };
