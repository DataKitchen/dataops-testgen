const Streamlit = {
    init: () => {
        sendMessageToStreamlit('streamlit:componentReady', { apiVersion: 1 });
    },
    setFrameHeight: (height) => {
        sendMessageToStreamlit('streamlit:setFrameHeight', { height: height });
    },
    sendData: (data) => {
        sendMessageToStreamlit('streamlit:setComponentValue', { value: data, dataType: 'json' });
    },
};

function sendMessageToStreamlit(type, data) {
    if (window.top) {
        window.top.postMessage(Object.assign({ type: type, isStreamlitMessage: true }, data), '*');
    }
}

export { Streamlit };
