import { app } from "../../../scripts/app.js"

const _ID = "CyberEve_LoopIndexSwitch";
const _PREFIX = "while_";
const _TYPE = "*"; 
const MAX_INPUTS = 100;

app.registerExtension({
    name: 'CyberEveLoop.LoopIndexSwitch',
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        // 添加调试信息
        console.log("Registering extension for:", nodeData.name);
        console.log("Looking for:", _ID);
        if (nodeData.name !== _ID) {
            return;
        }

        // 添加右键菜单选项
        const onGetExtraMenuOptions = nodeType.prototype.getExtraMenuOptions;
        nodeType.prototype.getExtraMenuOptions = function(_, options) {
            if (onGetExtraMenuOptions) {
                onGetExtraMenuOptions.apply(this, arguments);
            }
            
            // 添加输入槽
            options.push({
                content: "Add Loop Input",
                callback: () => {
                    // 弹出对话框让用户输入循环次数
                    const number = prompt("Enter loop iteration number (0-99):", "0");
                    if (number === null || isNaN(number)) {
                        return;
                    }

                    const num = parseInt(number);
                    if (num < 0 || num >= MAX_INPUTS) {
                        alert(`Please enter a number between 0 and ${MAX_INPUTS-1}`);
                        return;
                    }

                    const slotName = `${_PREFIX}${num}`;
                    
                    // 检查是否已存在该输入槽
                    if (this.inputs.find(input => input.name === slotName)) {
                        alert(`Input for iteration ${num} already exists!`);
                        return;
                    }
                    
                    // 添加新的输入槽
                    this.addInput(slotName, _TYPE);
                    this.graph.setDirtyCanvas(true);
                }
            });

            // 删除输入槽子菜单
            const valueInputs = this.inputs.filter(input => 
                input.name.startsWith(_PREFIX)
            );

            if (valueInputs.length > 0) {
                const removeOptions = valueInputs.map(input => ({
                    content: `Remove iteration ${input.name.substring(_PREFIX.length)}`,
                    callback: () => {
                        const index = this.inputs.findIndex(i => i.name === input.name);
                        if (index !== -1) {
                            this.removeInput(index);
                            this.graph.setDirtyCanvas(true);
                        }
                    }
                }));

                options.push({
                    content: "Remove Loop Input",
                    submenu: {
                        options: removeOptions
                    }
                });
            }
        };

        // 序列化节点时保存输入槽信息
        nodeType.prototype.serialize = function() {
            const data = LGraphNode.prototype.serialize.apply(this);
            data.inputSlots = this.inputs.filter(input => 
                input.name.startsWith(_PREFIX)
            ).map(input => ({
                name: input.name,
                type: input.type
            }));
            return data;
        };

        // 反序列化时恢复输入槽
        nodeType.prototype.configure = function(data) {
            LGraphNode.prototype.configure.apply(this, arguments);
            if (data.inputSlots) {
                // 移除所有循环相关的输入
                this.inputs = this.inputs.filter(input => 
                    !input.name.startsWith(_PREFIX)
                );
                // 恢复保存的输入槽
                data.inputSlots.forEach(slot => {
                    this.addInput(slot.name, slot.type);
                });
            }
        };
    }
});
