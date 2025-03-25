import subprocess
import json
import time
import threading
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Almacenamiento global para datos de Kubernetes
k8s_data = {
    "nodes": [],
    "pods": [],
    "services": [],
    "deployments": [],
    "last_updated": None
}

def run_kubectl_command(command, output_format="json"):
    """Ejecuta un comando kubectl y devuelve la salida"""
    try:
        # Si el comando es para obtener datos, usamos formato JSON
        if output_format == "json":
            result = subprocess.run(f"kubectl {command} -o json", shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                return {"error": result.stderr}
            return json.loads(result.stdout)
        # Si es otro tipo de comando (como delete o restart), no especificamos formato
        else:
            result = subprocess.run(f"kubectl {command}", shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                return {"error": result.stderr}
            return {"success": True, "message": result.stdout}
    except Exception as e:
        return {"error": str(e)}

def update_k8s_data():
    """Actualiza los datos de Kubernetes en segundo plano"""
    global k8s_data
    while True:
        try:
            # Obtener información de los nodos
            k8s_data["nodes"] = run_kubectl_command("get nodes")
            
            # Obtener información de los pods en todos los namespaces
            k8s_data["pods"] = run_kubectl_command("get pods --all-namespaces")
            
            # Obtener información de los servicios en todos los namespaces
            k8s_data["services"] = run_kubectl_command("get services --all-namespaces")
            
            # Obtener información de los deployments en todos los namespaces
            k8s_data["deployments"] = run_kubectl_command("get deployments --all-namespaces")
            
            # Registrar la última actualización
            k8s_data["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            
            print(f"Datos de Kubernetes actualizados a las {k8s_data['last_updated']}")
        except Exception as e:
            print(f"Error al actualizar datos: {str(e)}")
        
        # Esperar 5 minutos antes de la próxima actualización
        time.sleep(300)

@app.route('/')
def index():
    """Página principal del dashboard"""
    return serve_template()

@app.route('/api/data')
def get_data():
    """Endpoint API para obtener datos actualizados"""
    return jsonify(k8s_data)

@app.route('/api/restart', methods=['POST'])
def restart_resource():
    """Endpoint para reiniciar un recurso de Kubernetes"""
    data = request.json
    resource_type = data.get('type')
    namespace = data.get('namespace')
    name = data.get('name')
    
    if not all([resource_type, namespace, name]):
        return jsonify({"error": "Faltan parámetros requeridos"}), 400
    
    # Mapear tipo de recurso al comando correspondiente
    command_map = {
        "pod": f"delete pod {name} -n {namespace}",
        "deployment": f"rollout restart deployment {name} -n {namespace}",
        "service": f"rollout restart deployment $(kubectl get deployment -n {namespace} -l app={name} -o name) -n {namespace}"
    }
    
    if resource_type not in command_map:
        return jsonify({"error": f"Tipo de recurso no soportado: {resource_type}"}), 400
    
    # Ejecutar el comando SIN especificar formato de salida JSON
    result = run_kubectl_command(command_map[resource_type], output_format="text")
    return jsonify(result)

# HTML para la página principal
@app.route('/templates/index.html')
def serve_template():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Kubernetes Dashboard</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 0; padding: 20px; }
            h1, h2 { color: #326de6; }
            .container { max-width: 1200px; margin: 0 auto; }
            .section { margin-bottom: 30px; background: #f5f7fa; padding: 15px; border-radius: 5px; }
            table { width: 100%; border-collapse: collapse; }
            th, td { text-align: left; padding: 8px; border-bottom: 1px solid #ddd; }
            th { background-color: #326de6; color: white; }
            tr:hover { background-color: #f1f1f1; }
            .status-green { color: green; }
            .status-red { color: red; }
            .status-yellow { color: orange; }
            button { background-color: #326de6; color: white; border: none; padding: 5px 10px; cursor: pointer; }
            button:hover { background-color: #254baa; }
            .update-info { text-align: right; font-size: 12px; color: #666; }
        </style>
        <script>
            // Función para actualizar los datos automáticamente cada 5 minutos
            function setupAutoRefresh() {
                setInterval(refreshData, 300000); // 300000 ms = 5 minutos
                document.getElementById('last-update').textContent = new Date().toLocaleString();
            }
            
            // Función para refrescar los datos sin recargar la página
            function refreshData() {
                fetch('/api/data')
                    .then(response => response.json())
                    .then(data => {
                        updateUI(data);
                        document.getElementById('last-update').textContent = new Date().toLocaleString();
                    })
                    .catch(error => console.error('Error al obtener datos:', error));
            }
            
            // Función para actualizar la UI con nuevos datos
            function updateUI(data) {
                // Actualizar pods
                let podsTable = document.getElementById('pods-table');
                if (data.pods && data.pods.items) {
                    let podsHTML = '';
                    data.pods.items.forEach(pod => {
                        let status = pod.status.phase;
                        let statusClass = 'status-yellow';
                        if (status === 'Running') statusClass = 'status-green';
                        if (status === 'Failed') statusClass = 'status-red';
                        
                        podsHTML += `<tr>
                            <td>${pod.metadata.namespace}</td>
                            <td>${pod.metadata.name}</td>
                            <td class="${statusClass}">${status}</td>
                            <td><button onclick="restartResource('pod', '${pod.metadata.namespace}', '${pod.metadata.name}')">Reiniciar</button></td>
                        </tr>`;
                    });
                    document.getElementById('pods-body').innerHTML = podsHTML;
                }
                
                // Actualizar servicios
                if (data.services && data.services.items) {
                    let servicesHTML = '';
                    data.services.items.forEach(svc => {
                        let type = svc.spec.type || 'ClusterIP';
                        let ports = svc.spec.ports.map(p => `${p.port}:${p.targetPort}`).join(', ');
                        
                        servicesHTML += `<tr>
                            <td>${svc.metadata.namespace}</td>
                            <td>${svc.metadata.name}</td>
                            <td>${type}</td>
                            <td>${ports}</td>
                            <td><button onclick="restartResource('service', '${svc.metadata.namespace}', '${svc.metadata.name}')">Reiniciar</button></td>
                        </tr>`;
                    });
                    document.getElementById('services-body').innerHTML = servicesHTML;
                }
                
                // Actualizar deployments
                if (data.deployments && data.deployments.items) {
                    let deploymentsHTML = '';
                    data.deployments.items.forEach(deploy => {
                        let ready = `${deploy.status.readyReplicas || 0}/${deploy.status.replicas}`;
                        let statusClass = deploy.status.readyReplicas === deploy.status.replicas ? 'status-green' : 'status-yellow';
                        
                        deploymentsHTML += `<tr>
                            <td>${deploy.metadata.namespace}</td>
                            <td>${deploy.metadata.name}</td>
                            <td class="${statusClass}">${ready}</td>
                            <td><button onclick="restartResource('deployment', '${deploy.metadata.namespace}', '${deploy.metadata.name}')">Reiniciar</button></td>
                        </tr>`;
                    });
                    document.getElementById('deployments-body').innerHTML = deploymentsHTML;
                }
                
                // Actualizar hora de última actualización
                if (data.last_updated) {
                    document.getElementById('last-update').textContent = data.last_updated;
                }
            }
            
            // Función para reiniciar un recurso
            function restartResource(type, namespace, name) {
                if (!confirm(`¿Estás seguro de que deseas reiniciar ${type} "${name}" en namespace "${namespace}"?`)) {
                    return;
                }
                
                fetch('/api/restart', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        type: type,
                        namespace: namespace,
                        name: name
                    })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.error) {
                        alert(`Error: ${data.error}`);
                    } else {
                        alert(`${type} "${name}" reiniciado correctamente. Actualizando datos...`);
                        refreshData();
                    }
                })
                .catch(error => {
                    console.error('Error al reiniciar recurso:', error);
                    alert('Error al reiniciar recurso. Consulta la consola para más detalles.');
                });
            }
            
            // Inicializar al cargar la página
            window.onload = setupAutoRefresh;
        </script>
    </head>
    <body>
        <div class="container">
            <h1>Dashboard de Kubernetes</h1>
            <div class="update-info">
                Última actualización: <span id="last-update">-</span>
                <button onclick="refreshData()">Actualizar ahora</button>
            </div>
            
            <div class="section">
                <h2>Pods</h2>
                <table id="pods-table">
                    <thead>
                        <tr>
                            <th>Namespace</th>
                            <th>Nombre</th>
                            <th>Estado</th>
                            <th>Acciones</th>
                        </tr>
                    </thead>
                    <tbody id="pods-body">
                        <tr><td colspan="4">Cargando datos...</td></tr>
                    </tbody>
                </table>
            </div>
            
            <div class="section">
                <h2>Servicios</h2>
                <table id="services-table">
                    <thead>
                        <tr>
                            <th>Namespace</th>
                            <th>Nombre</th>
                            <th>Tipo</th>
                            <th>Puertos</th>
                            <th>Acciones</th>
                        </tr>
                    </thead>
                    <tbody id="services-body">
                        <tr><td colspan="5">Cargando datos...</td></tr>
                    </tbody>
                </table>
            </div>
            
            <div class="section">
                <h2>Deployments</h2>
                <table id="deployments-table">
                    <thead>
                        <tr>
                            <th>Namespace</th>
                            <th>Nombre</th>
                            <th>Estado</th>
                            <th>Acciones</th>
                        </tr>
                    </thead>
                    <tbody id="deployments-body">
                        <tr><td colspan="4">Cargando datos...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    return html

if __name__ == '__main__':
    # Iniciar el hilo para actualizar datos en segundo plano
    data_thread = threading.Thread(target=update_k8s_data, daemon=True)
    data_thread.start()
    
    # Ejecutar la aplicación Flask
    app.run(host='0.0.0.0', port=5000, debug=False)
